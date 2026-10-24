"""Shared program model produced by the loader and consumed by every phase and query."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ModInfo:
    name: str
    file: str
    is_stdlib: bool
    is_target: bool
    root: object  # canonical module SList
    is_external: bool = False
    text: str = ""
    purpose: str | None = None
    purpose_node: object = None
    uses: list = field(default_factory=list)  # Atoms
    export_nodes: list | None = None
    types: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)
    variants: dict = field(default_factory=dict)
    fns: dict = field(default_factory=dict)
    consts: dict = field(default_factory=dict)
    caps: dict = field(default_factory=dict)  # Capitalized name -> ("type"|"error"|"variant", info)
    exported_fns: set = field(default_factory=set)
    exported_consts: set = field(default_factory=set)
    exported_caps: set = field(default_factory=set)
    referenced_fns: set = field(default_factory=set)
    used: set = field(default_factory=set)

    @property
    def report(self) -> bool:
        return self.is_target or self.is_external


@dataclass
class ConstInfo:
    mod: ModInfo
    name: str
    node: object
    purpose: str = ""
    declared_type: tuple | None = None
    value: object = None
    clauses: dict = field(default_factory=dict)
    eval_state: int = 0  # 0: unvisited, 1: evaluating, 2: evaluated

    @property
    def qual(self) -> str:
        return f"{self.mod.name}.{self.name}"


@dataclass
class FnInfo:
    mod: ModInfo
    name: str
    node: object
    params: list = field(default_factory=list)  # [(name, type)]
    ret: tuple | None = None
    eff: frozenset = frozenset()
    fails: frozenset = frozenset()  # error ids
    clauses: dict = field(default_factory=dict)  # head -> [node]
    purpose: str = ""
    sig_ok: bool = False

    @property
    def qual(self) -> str:
        return f"{self.mod.name}.{self.name}"


@dataclass
class TypeInfo:
    mod: ModInfo
    name: str
    node: object
    params: tuple = ()  # declaration-scoped type variable names
    kind: str = "alias"  # alias | rec | sum | opaque (primitive-owned)
    fields: list = field(default_factory=list)
    variants: dict = field(default_factory=dict)
    alias_node: object = None
    alias_t: tuple | None = None
    busy: bool = False
    invalid_recursion: bool = False

    @property
    def qual(self) -> str:
        return f"{self.mod.name}.{self.name}"


@dataclass
class ErrInfo:
    mod: ModInfo
    name: str
    node: object
    fields: list = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.mod.name}.{self.name}" if self.mod.name else self.name


@dataclass
class VariantInfo:
    mod: ModInfo
    name: str
    tname: str
    fields: list
    vtype: tuple


@dataclass
class Program:
    pins: dict = field(default_factory=dict)  # stem -> dependency Pin
    modules: dict = field(default_factory=dict)
    available: dict = field(default_factory=dict)  # module name -> Path
    diags: list = field(default_factory=list)
    refs: dict = field(default_factory=dict)  # (module, node path) -> target
    calls: dict = field(default_factory=dict)  # fn qual -> set of fn quals
    type_index: dict = field(default_factory=dict)  # qual -> TypeInfo
    targets: list = field(default_factory=list)  # target module names, sorted
    discharged: dict = field(default_factory=dict)  # id(node) -> (file, line, col, path, fn_qual)
