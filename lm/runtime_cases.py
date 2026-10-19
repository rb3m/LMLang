"""Explicit effectful runtime fixture cases, separate from pure LM examples."""
from __future__ import annotations

import json
from pathlib import Path

from .interp import Interp
from .values import LmFail, show


def fixture_cases(prog, modules):
    """Yield (label, function, expected outcome) from MODULE.cases.json sidecars."""
    for mn in modules:
        m = prog.modules[mn]
        path = Path(m.file).with_suffix('.cases.json')
        if not path.is_file():
            continue
        for name, case in sorted(json.loads(path.read_text()).items()):
            f = m.fns[name]
            if f.params:
                raise ValueError(f'{path}: fixture function {f.qual} must take no parameters')
            yield f'{mn}/{name}/case', f, (case.get('kind', 'ok'), case['expected'])


def fixture_outcomes(prog, modules):
    from .runner import in_big_stack, runtime_diag

    def go():
        results = {}
        for label, f, _ in fixture_cases(prog, modules):
            it = Interp(prog, allowed=f.eff, contracts=True, seed=0)
            try:
                results[label] = ('ok', show(it.call_fn(f, [])))
            except LmFail as ex:
                results[label] = ('fail', f'(fail {ex.id}' + ''.join(' ' + show(a) for a in ex.args_) + ')')
            except Exception as ex:
                d = runtime_diag(ex, it=it)
                if d is None:
                    raise
                results[label] = ('fault', d.code)
        return results

    return in_big_stack(go)
