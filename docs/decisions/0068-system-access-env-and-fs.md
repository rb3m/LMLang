# ADR-068 Backlog 14: system access (env, more fs, effects env.read and fs.delete) (2026-10-19, agent consensus)

Context: programs could not read a config token or `$HOME`, keep a log, or walk a folder: fs had only whole-file read, write and exists.

Decision:
1. Two new effects in the closed set: `env.read`, and `fs.delete` for operations that remove a name, so `--allow fs.write` never silently authorizes deletion. (`fs.write` can still truncate a file: that is not a general data-loss guard.)
2. Module `env`: `lookup(name) -> (Opt Str)` (env.read, total). `Some ""` when set but empty; None when unset or for an empty name or one containing `=` or NUL; invalid UTF-8 decoded with U+FFFD as for io.args (ADR-063). No writes. (`get` is reserved, ADR-047.)
3. `fs` additions, all failing `fs.IoError`, paths used as given: `append` (fs.write; creates, no separator, no atomicity); `entries` (fs.read; names sorted by code point, IoError on non-UTF-8 names or a non-directory; `list` would collide with the special form); `is-dir` (follows links; false if missing); `make-dir` (one level; fails on any existing entry); `remove` (fs.delete; file, the symlink itself, or an empty directory, never recursive); `rename` (fs.write and fs.delete; never overwrites, IoError.path is `from`).
4. No-overwrite rename without a portable "rename-no-replace" call in Python or Go stdlib: a non-directory claims the destination name atomically (hard link, or a new symlink with the same target for a symlink, both fail if the name exists), then unlinks the source; cross-device or unsupported links fail, with no copy fallback. A directory is checked (lstat) then renamed: a racing writer can at worst lose an empty directory created in between, never data.
5. Identical in interpreter, Go and Python targets (differential test). Subprocesses are not included: backlog 25, an owner decision.

Revisit when: a Python or Go stdlib gains rename-no-replace, or a program needs recursive delete or directory walking.

Who agreed: agy and Codex (gpt-6.1-sol) agreed on the effects, env and the deferral of subprocesses; both required `rename` to need fs.write as well. Codex renamed `get`/`list` to `lookup`/`entries`, pinned empty/invalid env names, symlink behavior, invalid UTF-8 names and race-free no-overwrite; agy pinned EXDEV and symlink rules. Implementation by Codex (gpt-6.1-sol); Claude replaced a hard-coded Darwin linkat syscall with the portable symlink-recreate path.
