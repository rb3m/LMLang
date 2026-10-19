"""Validate regular recursive declarations before transparent alias expansion."""
from __future__ import annotations

from .sexpr import Atom, SList


def _references(info, index):
    def target(name):
        qual = name if "." in name else f"{info.mod.name}.{name}"
        return qual if qual in index else None

    def visit(node, path):
        if isinstance(node, Atom):
            hit = target(node.value) if node.kind == "type" else None
            if hit:
                yield hit, (), node, path
            return
        if not node.items:
            return
        first = node.items[0]
        hit = target(first.value) if isinstance(first, Atom) and first.kind == "type" else None
        if hit:
            yield hit, node.items[1:], node, path
        for i, child in enumerate(node.items):
            if i == 0 and hit:
                continue
            yield from visit(child, f"{path}/{i}")

    for i, body in enumerate(info.node.items[2:], 2):
        yield from visit(body, f"{info.mod.name}/{info.name}/{i}")


def _components(graph):
    """Tarjan SCCs; declaration graphs are small and deterministic."""
    stack, active, numbers, lows = [], set(), {}, {}
    groups = []

    def visit(name):
        numbers[name] = lows[name] = len(numbers)
        stack.append(name)
        active.add(name)
        for other in graph[name]:
            if other not in numbers:
                visit(other)
                lows[name] = min(lows[name], lows[other])
            elif other in active:
                lows[name] = min(lows[name], numbers[other])
        if lows[name] != numbers[name]:
            return
        group = set()
        while True:
            other = stack.pop()
            active.remove(other)
            group.add(other)
            if other == name:
                break
        groups.append(group)

    for name in graph:
        if name not in numbers:
            visit(name)
    return groups


def check_regular_recursion(resolver):
    index = resolver.prog.type_index
    refs = {name: list(_references(info, index)) for name, info in index.items()}
    graph = {name: [ref[0] for ref in targets] for name, targets in refs.items()}
    for group in _components(graph):
        recursive = len(group) > 1 or any(name in graph[name] for name in group)
        if not recursive:
            continue
        # Alias expansion may only cross a cycle when a nominal declaration stops it.
        aliases = {name for name in group if index[name].kind == "alias"}
        alias_graph = {name: [n for n in graph[name] if n in aliases] for name in aliases}
        for cycle in _components(alias_graph):
            if len(cycle) > 1 or any(name in alias_graph[name] for name in cycle):
                for name in cycle:
                    info = index[name]
                    resolver.diag(info.mod, "E-CYCLE", info.node,
                                  f"{info.mod.name}/{info.name}",
                                  f"type alias `{info.name}` refers to itself")
        for name in group:
            info = index[name]
            for target, args, node, path in refs[name]:
                if target not in group:
                    continue
                names = tuple(a.value if isinstance(a, Atom) and a.kind == "sym" else None
                              for a in args)
                if names == info.params and len(args) == len(index[target].params):
                    continue
                for member in group:
                    index[member].invalid_recursion = True
                resolver.diag(info.mod, "E-TYPE", node, path,
                              "recursive type references must preserve "
                              "declaration parameters in order")
