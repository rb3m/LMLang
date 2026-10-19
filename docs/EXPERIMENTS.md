# Experiments: trying LM on real scripts and applications

Status 2026-10-17: the toolchain (M0-M12) is complete enough to write programs in `src/`. The open question is whether the agent workflow pays off on long scripts and applications, not only on the 13 small benchmark tasks (whose caveats are in ADR-024).

## How to run one
1. Describe the program to the agent in domain terms. The agent writes it under `src/` (one module per file, `purpose`/`sig` on every function and `example` on every pure one; effectful functions get runtime cases instead, docs/TESTING.md), working only through `index`, `slice` and `edit` once the project has more than a few modules.
2. The agent proposes acceptance scenarios (`tests/accept/*.accept`, status `proposed`) and walks you through them with `python3 -m lm accept --review`. When you explicitly approve them in conversation, the agent runs `python3 -m lm accept --approve DIGEST.. --by "<words>"`. (Interactive `lm accept --bless` remains available if you prefer).
3. Loop: you ask for a change, the agent edits, and must finish with `check`, `test`, `accept --guard` all green. Use `python3 -m lm explain mod.fn` when you want a function described in plain words.
4. Try to break it: give the agent an input you expect to be mishandled; it becomes a new proposed scenario.

## What to record (so the next session can decide what to build)
Append to docs/EVIDENCE.md, one row per finding: date, what you tried, what worked, what hurt. Useful signals: tokens the agent spent reading vs a plain-Python baseline, number of check/test iterations per change, bugs that reached you despite scenarios, features the agent wanted but LM lacked (add them to the ROADMAP backlog).

## Known gaps that will bite on longer programs (all in the ROADMAP backlog)
- Float is binary64 and finite-only (ADR-039): money should still be fixed-point Ints (cents); there is no `Decimal` yet.
- I/O: `io.args`, `io.read-line`, `io.read-all`, `io.eprint`, `fs.read/write/exists` (M8); clock and seedable randomness in `time`/`rand` and JSON in `json` (M12). No networking/HTTP yet.
- Strings: split, trim, to-int (returns Opt), lines, contains, starts-with, substring, index-of, replace, ASCII case; no Unicode casing, no character type.
- No tuples; lists are accessed by `list.at`/`list.nth`, list patterns, or `map/filter/fold/any/all/map2/index-of`. `Map`/`Set` exist since M11 (modules `map`, `set`; literals `mapof`/`setof`).
- Tree-walking interpreter: fine for tests, slow for heavy loops; ship scripts as native binaries with `lm build` (about 60x faster on `examples/colsum.lm`).
- No module-level constants (group with a `(Map K V)` and `map.update`, see `examples/colsum.lm`).
- Running on the server: DreamHost has Python 3.12, so the interpreter should run there as-is (copy the repo, `python3 -m lm run ...`); untested so far (ADR-027).
- Slice savings are unproven on large projects (S1 against a single module is about 50%, not 4%).

## Ground rules that still apply
Agents never approve scenarios on their own judgment, edit `accept.lock` by hand, or run `accept --bless`. AGENTS.md is updated whenever structure, commands or status change. Decisions go in docs/decisions/ as new ADR files (never rewrite an accepted one).
