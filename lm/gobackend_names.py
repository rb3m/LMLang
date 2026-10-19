"""Shared Go name mangling and string literals; independent of the emitters."""
import json


def mangle(name: str, prefix: str) -> str:
    """`list.index-of` -> F_list_X_index_of. LM names have no `_` or uppercase X, so this is injective."""
    return prefix + name.replace("-", "_").replace(".", "_X_")


def local(name: str) -> str:
    return "v_" + name.replace("-", "_")


def prim_name(p: str) -> str:
    return "prim_" + p.replace(".", "_").replace("-", "_")


def golit(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


