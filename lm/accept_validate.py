"""Static acceptance validation, shared by check and scenario execution."""
from __future__ import annotations

from pathlib import Path

from .diag import make
from .prelude import EFFECTS
from .sexpr import Atom, SList, read


def validate(prog, ck, s):
    from .accept import check_args, external_value

    if s.problem:
        return None, 'invalid scenario: ' + s.problem
    m = prog.modules.get(s.module)
    sym = s.run.items[1].value
    name = sym.split('.', 1)[1]
    f = m.fns.get(name) if m else None
    if f is None:
        return None, f'unknown function {sym}'
    if not m.is_target and name not in m.exported_fns:
        return None, f'function {sym} is not exported'
    unknown = set(s.allow) - EFFECTS
    if unknown:
        return None, 'unknown effect(s): ' + ' '.join(sorted(unknown))
    missing = f.eff - set(s.allow)
    if missing:
        return None, 'missing declared effect(s): ' + ' '.join(sorted(missing))
    raw_nodes = list(s.run.items[2:])
    if len(raw_nodes) != len(f.params):
        return None, (f'{sym} takes {len(f.params)} argument(s), '
                      f'scenario gives {len(raw_nodes)}')
    kind = s.exp.items[0].value
    if kind == 'expect-fail':
        err = s.exp.items[1]
        error_name = (err.value if isinstance(err, Atom)
                      and err.kind == 'type' else '')
        if error_name in m.errors:
            qualified = f'{m.name}.{error_name}'
            return None, ('does not type-check: outside a module write its '
                          f'names qualified: `{qualified}`')
        own_error = (isinstance(error_name, str)
                     and error_name.startswith(m.name + '.')
                     and error_name.split('.', 1)[1] in m.errors)
        if not own_error and error_name not in ('DivZero', 'OutOfRange'):
            return None, (
                'expect-fail needs a qualified error name of the '
                'target module or a prelude error: ' + str(error_name))
    before = len(prog.diags)
    exp_node = want_node = None
    try:
        nodes, ft = check_args(ck, m, f, raw_nodes)
        if kind == 'expect':
            exp_node = external_value(ck, m, s.exp.items[1], 'expect')
            ck.clear_facts()
            t = ck.sandbox(m, 'the expected value',
                           lambda: ck.infer(m, exp_node, {}, 'expect'))
            ck.expect(m, ft[2], t, exp_node, 'expect', 'expected value')
        if kind == 'expect-fail':
            want_node = external_value(
                ck, m, SList((Atom('sym', 'fail'), *s.exp.items[1:])),
                'expect-fail')
            for arg in want_node.items[2:]:
                ck.clear_facts()
                ck.sandbox(m, 'an expected error argument',
                           lambda arg=arg: ck.infer(m, arg, {}, 'expect-fail'))
            ck.infer(m, want_node, {}, 'expect-fail')
        ck.check_eq(m)
        errors = [d for d in prog.diags[before:] if d.severity == 'error']
    finally:
        del prog.diags[before:]
    if errors:
        return None, 'does not type-check: ' + errors[0].msg
    return (m, f, nodes, kind, exp_node, want_node), None


def scenario_diags(prog, ck, directory='tests/accept'):
    """Return E-SCENARIO diagnostics without interpreting scenario values."""
    from .accept import Scenario

    out, seen = [], set()
    for file in sorted(Path(directory).glob('*.accept')):
        node, diags = read(file.read_text(encoding='utf-8'), str(file))
        if node is None:
            out.extend(make('E-SCENARIO', str(file), d.line, d.col, d.msg)
                       for d in diags)
            continue
        if not (isinstance(node, SList) and node.items
                and getattr(node.items[0], 'value', None) == 'scenarios'):
            out.append(make(
                'E-SCENARIO', str(file), node.line, node.col,
                'file must be one (scenarios (scenario ..) ..) form'))
            continue
        for child in node.items[1:]:
            s = Scenario(child, str(file))
            if s.name in seen and s.problem is None:
                s.problem = f'duplicate scenario name {s.name!r}'
            seen.add(s.name)
            _, problem = validate(prog, ck, s)
            if problem:
                out.append(make('E-SCENARIO', str(file), child.line, child.col,
                                problem, path=f'scenario:{s.name}'))
    return out
