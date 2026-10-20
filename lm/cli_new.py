"""`lm new DIR`: scaffold a project directory that passes check, test, fmt and accept out of the box."""
from __future__ import annotations

import re
import sys
from pathlib import Path

NAME_RE = re.compile(r"[a-z][a-z0-9-]*")
REPO = Path(__file__).resolve().parent.parent

PROGRAM = '''(module {name}
  (purpose "Starter program: greets the names given on the command line.")
  (use io str)
  (export greeting main)
  (fn greet-all
    (purpose "Print one greeting per name.")
    (sig (names (List Str)) -> Unit)
    (eff io.out)
    (body (match names ((list) unit) ((cons n rest) (do (io.print (greeting n)) (greet-all rest))))))
  (fn greeting
    (purpose "Greeting for one name.")
    (sig (who Str) -> Str)
    (example ("Ana") => "Hello, Ana!")
    (body (str.concat (str.concat "Hello, " who) "!")))
  (fn main
    (purpose "Entry point: greet each argument, or the world when there are none; exit status 0.")
    (sig -> Int)
    (eff io.in io.out)
    (body (do (greet-all (match (io.args) ((list) (list "world")) (names names))) 0))))
'''

SCENARIOS = '''(scenarios
  (scenario "Greets a name"
    (status proposed)
    (why "Given the name Ana, the greeting is exactly: Hello, Ana!")
    (run {name}.greeting "Ana")
    (expect "Hello, Ana!")))
'''

AGENT_GUIDE = '''# AGENTS.md: {name} (an LM project)
LM is a programming language for AI agents: s-expression syntax, every function declares purpose, signature, effects, failures and examples, and the toolchain answers structured queries. Run `lm guide` once before writing code (syntax, workflow, stdlib); `lm help CMD` for any command.
## Where things are
- Toolchain: `{repo}/bin/lm` (use this path if `lm` is not on PATH).
- Worked programs to copy patterns from: `{repo}/examples/README.md`. Full language rules: `{repo}/docs/SPEC.md` (search by heading, only when `lm guide` is not enough).
## Loop
1. Orient: `lm index`; `lm index --stdlib --modules`, then `--module M`; `lm slice {name}.FN`.
2. Change code with `lm edit` ops (`lm help edit`), not by rewriting files. `lm fmt` sorts definitions by name; use `lm edit` ops, or re-read the file after fmt before text edits.
3. `lm check` then `lm test` until both are clean; fix diagnostics by their code and path.
4. `lm run {name}.main --allow io.in --allow io.out -- ARGS` to try it; `lm build {name}.main` for a native binary (needs Go) or `--target py`.
## Scenarios (the human's spec)
- tests/accept/*.accept hold behavior the human approves. Add new ones with (status proposed).
- Walk the human through each with `lm accept --review`. Only after their explicit yes: `lm accept --approve DIGEST --by "<their words>"` (`--retire NAME --by ..` for renamed or deleted ones).
- Never approve on your own judgment, never edit accept.lock, never run `--bless`.
## Done
`lm check`, `lm test` and `lm accept --guard` are all green.
'''

NEXT_STEPS = '''created {dir}/ (module `{name}`). Next:
  cd {dir}
  # Read AGENTS.md, then:
  lm guide
  lm check && lm test   # static checks, then every example
  lm run {name}.main --allow io.in --allow io.out -- Ana Bo
  lm build {name}.main && ./{name} Ana   # native binary (needs Go)
  lm accept --review   # scenarios waiting for your approval
'''


def _write_project(target: Path, name: str) -> None:
    files = {
        Path("src") / f"{name}.lm": PROGRAM.format(name=name),
        Path("tests") / "accept" / f"{name}.accept": SCENARIOS.format(name=name),
        Path(".gitignore"): f"/{name}\n",
        Path("AGENTS.md"): AGENT_GUIDE.format(name=name, repo=REPO),
        Path("CLAUDE.md"): "See AGENTS.md.\n",
        Path("GEMINI.md"): "See AGENTS.md.\n",
    }
    for rel, text in files.items():
        (target / rel).parent.mkdir(parents=True, exist_ok=True)
        (target / rel).write_text(text)


def cmd_new(args) -> int:
    if len(args) != 1 or args[0].startswith("-"):
        sys.stderr.write("usage: lm new DIR   (DIR's last part becomes the module name: lowercase, digits, dashes)\n")
        return 3
    target = Path(args[0])
    name = target.name
    if not NAME_RE.fullmatch(name):
        sys.stderr.write(f"lm new: `{name}` is not a module name; use lowercase letters, digits and dashes, starting with a letter\n")
        return 3
    if target.exists() and any(target.iterdir()):
        sys.stderr.write(f"lm new: {target} exists and is not empty; nothing written\n")
        return 3
    try:
        _write_project(target, name)
    except OSError as e:
        sys.stderr.write(f"lm new: cannot write {target}: {e.strerror or e}\n")
        return 1
    sys.stdout.write(NEXT_STEPS.format(dir=target, name=name))
    return 0
