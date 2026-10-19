# Contributing

Read [AGENTS.md](AGENTS.md) first. Orient with `lm index`, then `lm slice MOD.FN`; run `lm callers` before changing a signature. Use `lm edit` operations for LM changes and loop through `lm check` and `lm test`.

Before declaring a change complete, run:

```sh
python3 -m unittest discover tests/unit
bin/lm check
bin/lm test
bin/lm accept --guard
scripts/export-public.sh . --scan-only
```

Python code must use only the standard library, support Python >= 3.10, and keep modules below roughly 400 lines. New behavior and bug fixes need a failing spec fixture first. Keep code and SPEC aligned; document real design alternatives in a new ADR under `docs/decisions/` and follow the design consensus rule in AGENTS.md.

Write acceptance scenarios as proposed and walk the project owner through their intent, input, expected result and current behavior. Only the human owner approves scenarios. Agents may run `lm accept --approve DIGEST.. --by "<their words>"` only after the human's explicit yes; never approve by agent judgment, edit `accept.lock` by hand, or run `--bless` as an agent.
