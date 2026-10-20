"""Mechanical source cleaning and namespace wrapping for embedded runtimes."""


def clean_source(text: str) -> str:
    lines = []
    for line in text.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("from .") or trimmed.startswith("from __future__"):
            continue
        lines.append(line)
    return "\n".join(lines)


def wrap_module(text: str, ns_name: str) -> str:
    cleaned = clean_source(text)
    indented = "\n".join(("\t" + line if line.strip() else "")
                         for line in cleaned.splitlines())
    return (
        f"def _make_{ns_name}():\n"
        f"{indented}\n"
        f"\tclass _Mod: pass\n"
        f"\t_m = _Mod()\n"
        f"\tfor _k, _v in list(locals().items()):\n"
        f"\t\tif not _k.startswith('_make_'): setattr(_m, _k, _v)\n"
        f"\treturn _m\n"
        f"{ns_name} = _make_{ns_name}()\n"
    )
