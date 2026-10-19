"""Tracked public-tree export and fail-closed privacy scan (stdlib only)."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

EXCLUDED = {"docs/ENVIRONMENT.md"}
# Exact example addresses allowed in fixtures: none currently present.
# das@FreeBSD.ORG: third-party copyright holder, reproduced verbatim (THIRD_PARTY_NOTICES.md).
EMAIL_ALLOWED = {"noreply@anthropic.com", "das@FreeBSD.ORG"}
# Exact placeholder / CI account paths allowed: /home/runner; no others present.
PATH_ALLOWED = {"/home/runner"}
EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
IP = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
PERSONAL_PATH = re.compile(r"/(?:home|Users)/[^/\s\"'`<>:;)]+|/Vol" + r"umes/[^\s\"'`<>]*")
# Split personal identifiers so the scanner can scan its own source.
WORDS = re.compile(r"\b(?:" + "|".join(("Ba" + "ca", "Alder" + "aan",
                   "ro" + "bertoEX", "home" + "server", "M4" + "Mac")) + r")\b", re.I)
OWNER_NAME = re.compile("Ro" + "berto", re.I)


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def tracked(root):
    return [os.fsdecode(p) for p in git(root, "ls-files", "-z").split(b"\0") if p]


def scan(root, paths):
    failed = False
    for name in paths:
        if name in EXCLUDED:
            continue
        path = root / name
        for parent in path.parents:
            if parent == root:
                break
            if parent.is_symlink():
                raise ValueError(f"scan path has symlink ancestor: {name}")
        # Do not follow symlinks outside the exported tree.
        if path.is_symlink():
            data = os.fsencode(os.readlink(path))
        else:
            data = path.read_bytes()  # Missing/unreadable files fail closed.
        if b"\0" in data:
            continue
        text = data.decode("utf-8", errors="surrogateescape")
        for number, line in enumerate(text.splitlines(), 1):
            matches = []
            for match in EMAIL.finditer(line):
                value = match.group()
                if value not in EMAIL_ALLOWED and not value.endswith("@users.noreply.github.com"):
                    matches.append(value)
            for match in IP.finditer(line):
                octets = [int(x) for x in match.group().split(".")]
                a, b, c, d = octets
                if max(octets) <= 255 and (a == 10 or (a == 172 and 16 <= b <= 31)
                                          or (a == 192 and b == 168)):
                    matches.append(match.group())
            matches.extend(m.group() for m in PERSONAL_PATH.finditer(line)
                           if m.group() not in PATH_ALLOWED)
            matches.extend(m.group() for m in WORDS.finditer(line))
            if name != "NOTICE":
                matches.extend(m.group() for m in OWNER_NAME.finditer(line))
            for value in sorted(set(matches)):
                print(f"{name}:{number}:{value}")
                failed = True
    return not failed


def remove(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def sync(stage, dest, source):
    if dest.is_symlink():
        raise ValueError("DEST must not be a symlink")
    dest = dest.resolve()
    if dest == source or dest in source.parents or source in dest.parents:
        raise ValueError("DEST must be separate from the source checkout")
    if dest.is_symlink() or (dest.exists() and not dest.is_dir()):
        raise ValueError("DEST must be a directory")
    if dest.exists() and any(dest.iterdir()):
        if not (dest / ".git").exists():
            raise ValueError("DEST must be empty, nonexistent, or a git repository")
        if Path(os.fsdecode(git(dest, "rev-parse", "--show-toplevel")).strip()).resolve() != dest:
            raise ValueError("DEST must be a git repository root")
        old = tracked(dest)
        for name in old:
            for parent in (dest / name).parents:
                if parent == dest:
                    break
                if parent.is_symlink():
                    raise ValueError(f"DEST tracked path has symlink ancestor: {name}")
        new = [p.relative_to(stage) for p in stage.rglob("*") if p.is_file() or p.is_symlink()]
        # Refuse to overwrite any untracked destination content, including ancestors.
        old_set = set(old)
        for rel in new:
            target = dest / rel
            for parent in target.parents:
                if parent == dest:
                    break
                if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                    raise ValueError(f"DEST path obstructed: {rel}")
            if (target.exists() or target.is_symlink()) and str(rel) not in old_set:
                raise ValueError(f"DEST untracked path obstructed: {rel}")
        for name in old:
            if name == ".git" or name.startswith(".git/"):
                raise ValueError("refusing to touch DEST/.git")
            path = dest / name
            if path.exists() or path.is_symlink():
                # A tracked file replaced locally by a directory may contain untracked data.
                if path.is_dir() and not path.is_symlink():
                    raise ValueError(f"DEST tracked file is now a directory: {name}")
                path.unlink()
                parent = path.parent
                while parent != dest:
                    try:
                        parent.rmdir()  # Remove only empty directories, keeping untracked data.
                    except OSError:
                        break
                    parent = parent.parent
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(stage, dest, dirs_exist_ok=True, symlinks=True)
    print("Export ready. Next steps (review first):")
    import shlex
    quoted = shlex.quote(str(dest))
    print(f"git -C {quoted} add -A")
    print(f"git -C {quoted} commit")


def main():
    if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != "--scan-only"):
        print("usage: scripts/export-public.sh DEST [--scan-only]", file=sys.stderr)
        return 1
    root = Path(os.fsdecode(git(Path.cwd(), "rev-parse", "--show-toplevel")).strip()).resolve()
    if len(sys.argv) == 3:
        return 0 if scan(root, tracked(root)) else 1
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("refusing export: uncommitted changes to tracked files")
    with tempfile.TemporaryDirectory(prefix="lm-public-") as tmp:
        stage = Path(tmp) / "stage"
        stage.mkdir()
        archive = Path(tmp) / "head.tar"
        with archive.open("wb") as output:
            subprocess.run(["git", "-C", str(root), "archive", "HEAD"], stdout=output, check=True)
        # Git creates this archive from tracked paths; no external archive is accepted.
        with tarfile.open(archive) as tar:
            tar.extractall(stage)
        for name in EXCLUDED:
            path = stage / name
            for parent in path.parents:
                if parent == stage:
                    break
                if parent.is_symlink():
                    raise ValueError(f"excluded path has symlink ancestor: {name}")
            if path.exists() or path.is_symlink():
                remove(path)
        paths = [p.relative_to(stage).as_posix() for p in stage.rglob("*")
                 if p.is_file() or p.is_symlink()]
        if not scan(stage, sorted(paths)):
            return 1
        sync(stage, Path(sys.argv[1]), root)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
        print(f"export-public: {error}", file=sys.stderr)
        sys.exit(1)
