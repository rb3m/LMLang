"""Acceptance scenario execution, review, and guard commands."""
from __future__ import annotations

import sys

from .cli_common import USAGE, _flags, _report, _static


def cmd_accept(args) -> int:
    from . import accept as A

    try:
        flags, pos = _flags(args, {"--review": False, "--guard": False, "--bless": False, "--approve": False, "--retire": False, "--by": True, "--dir": True, "--lock": True})
    except ValueError as ex:
        sys.stderr.write(f"lm accept: {ex}\n" + USAGE)
        return 3
    d, lockf = flags.get("--dir", "tests/accept"), flags.get("--lock", "accept.lock")
    scs, bad = A.load_scenarios(d)
    for b in bad:
        print("BAD       " + b)
    lock = A.read_lock(lockf)
    gprobs = A.guard(scs, lock)
    if "--approve" in flags:
        by_text = flags.get("--by")
        if by_text is None:
            sys.stderr.write("lm accept --approve: missing --by \"TEXT\"\n")
            return 1
        if bad:
            sys.stderr.write("lm accept --approve: refused due to bad scenario(s)\n")
            return 1
        chosen = [s for s in scs if s.problem is None and s.digest() in pos]
        if chosen:
            mods = sorted({s.module for s in chosen})
            prog, ck = _static([], extra=mods)
            if any(d.severity == 'error' for d in prog.diags):
                _report(prog.diags, lambda e, w: '')
                sys.stderr.write('lm accept --approve: fix check errors first\n')
                return 1
            for s in chosen:
                _, problem = A.validate(prog, ck, s)
                if problem:
                    sys.stderr.write(f'lm accept --approve: {s.name}: {problem}\n')
                    return 1
        try:
            approved, already = A.approve(scs, lockf, pos, by_text)
        except ValueError as ex:
            sys.stderr.write(f"lm accept --approve: {ex}\n")
            return 1
        for s in already:
            print(f"note: already approved and locked: {s.name} ({s.digest()})")
        for s in approved:
            print(f"approved {s.digest()} {s.name}")
        return 0
    if "--retire" in flags:
        try:
            retired = A.retire(scs, lockf, pos, flags.get("--by") or "")
        except ValueError as ex:
            sys.stderr.write(f"lm accept --retire: {ex}\n")
            return 1
        for n, dig in retired:
            print(f"retired {dig} {n}")
        return 0
    if "--bless" in flags:
        if not sys.stdin.isatty():
            sys.stderr.write("lm accept --bless: refused. Only the human blesses scenarios, from an interactive terminal. Use `lm accept --approve DIGEST.. --by \"TEXT\"` to record owner approval.\n")
            return 1
        new = {s.name: s.digest() for s in scs if s.status == "approved" and s.problem is None}
        for n in sorted(set(new) | set(lock)):
            tag = "added   " if n not in lock else "removed " if n not in new else "changed " if new[n] != lock[n] else None
            if tag:
                print(tag + n)
        if input("write accept.lock with these approved scenarios? [y/N] ").strip().lower() != "y":
            return 1
        A.write_lock(lockf, scs)
        sys.stderr.write(f"blessed {len(new)} scenario(s)\n")
        return 0
    if "--guard" in flags:
        for g in gprobs:
            print(g)
        sys.stderr.write("guard: " + ("OK" if not gprobs else f"{len(gprobs)} problem(s)") + "\n")
        return 1 if gprobs or bad else 0
    mods = sorted({s.module for s in scs if s.module})
    prog, ck = _static([], extra=mods)
    if prog.diags and any(x.severity == "error" for x in prog.diags):
        _report(prog.diags, lambda e, w: "")
        sys.stderr.write("accept: not run (fix check errors first)\n")
        return 1
    rows, fails, ok_n, appr, prop = [], 0, 0, 0, 0
    for s in scs:
        ok, detail = A.execute(prog, ck, s)
        d_tag = f"{s.digest()}  " if "--review" in flags and s.problem is None else ""
        name_col = f"{d_tag}{s.name}"
        if s.status == "approved":
            appr += 1
            ok_n += ok
            fails += not ok
            rows.append(f"{'PASS' if ok else 'FAIL'}  approved  {name_col:<32} {s.describe() if s.problem is None else ''}" + ("" if ok else f"  [{detail}]"))
        elif "--review" in flags or True:
            prop += s.status == "proposed"
            if s.status == "proposed":
                rows.append(f"----  proposed  {name_col:<32} needs your OK")
                if "--review" in flags:
                    rows.append(f"            why: {s.why}")
                    if s.problem is None:
                        rows.append(f"            case: {s.describe()}")
                    rows.append(f"            program today: {'matches' if ok else detail}")
            else:
                rows.append(f"BAD   invalid   {name_col:<32} {detail}")
                fails += 1
    for r in rows:
        print(r)
    for g in gprobs:
        print(g)
    print(f"Summary: {appr} approved ({ok_n} pass, {fails} FAIL) · {prop} proposed · guard {'OK' if not gprobs else 'FAILED'}")
    return 1 if fails or gprobs or bad else 0

