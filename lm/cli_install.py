"""Link the checkout's CLI and agent skill into user directories."""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
USAGE = "usage: lm install [--bin DIR] [--uninstall]\n"


def _link_status(path: Path, target: Path, uninstall: bool) -> str:
    if path.is_symlink():
        try:
            ours = path.resolve() == target
        except RuntimeError:  # A symlink loop is a foreign link, too.
            ours = False
        if not ours:
            return "conflict"
        if uninstall:
            path.unlink()
            return "removed"
        return "ok"
    if path.exists():
        return "conflict"
    if uninstall:
        return "absent"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)
    return "linked"


def cmd_install(args) -> int:
    bin_arg = None
    uninstall = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--uninstall" and not uninstall:
            uninstall = True
            i += 1
            continue
        if (arg == "--bin" and bin_arg is None and i + 1 < len(args)
                and args[i + 1] and not args[i + 1].startswith("-")):
            bin_arg = args[i + 1]
            i += 2
            continue
        sys.stderr.write(USAGE)
        return 3

    try:
        home = Path.home()
        bin_dir = Path(bin_arg) if bin_arg is not None else home / ".local/bin"
        links = [(bin_dir / "lm", REPO / "bin/lm")]
        for root, skills in (
            (home / ".claude", home / ".claude/skills"),
            (home / ".codex", home / ".agents/skills"),
            (home / ".gemini", home / ".gemini/skills"),
        ):
            if not root.is_dir():
                print(f"skip {skills} (no {root})")
                continue
            links.append((skills / "lm", REPO / "skills/lm"))

        failed = False
        for path, target in links:
            try:
                status = _link_status(path, target, uninstall)
            except OSError as e:
                sys.stderr.write(f"lm install: {path}: {e}\n")
                failed = True
                continue
            print(f"{status} {path}")
            failed |= status == "conflict"

        if not uninstall:
            path_dirs = {Path(entry).resolve()
                         for entry in os.environ.get("PATH", "").split(os.pathsep)}
            if bin_dir.resolve() not in path_dirs:
                sys.stderr.write(f"lm install: warning: add {bin_dir.resolve()} to PATH\n")
        return 1 if failed else 0
    except OSError as e:
        sys.stderr.write(f"lm install: {e}\n")
        return 1
