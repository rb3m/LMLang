# ADR-080 Backlog 28: agent skill `skills/lm/SKILL.md` and `lm install` (2026-10-27, agent consensus)

Status: accepted (2026-10-27). Owner asked for a skill so agents outside this repo can find and start using LM, installed for Claude Code, Codex and Antigravity on both owner Macs.

Context: agents outside the repo do not know LM exists. Onboarding already exists (`lm guide`, `lm new` writes a project AGENTS.md); what is missing is discovery and a way to get `lm` on PATH.

Options: (1) copy SKILL.md by hand into each agent's skills dir; (2) a shell install script; (3) an `lm install` command (stdlib Python) that symlinks the wrapper and the skill.

Decision (agy, Codex, Claude agree on 3):
- Skill source is `skills/lm/SKILL.md` in the repo and ships in the public export. Frontmatter `name` and `description` only; body about 10 lines that point to `lm guide`, `lm new`, the project AGENTS.md and the check/test loop. No syntax or spec text, so the guide stays the single source of truth and the skill cannot drift. A unit test caps its size.
- `lm install [--bin DIR] [--uninstall]` links `<bin>/lm` (default `~/.local/bin`) to `bin/lm`, and `lm` in each agent's user skills dir to `skills/lm`: `~/.claude/skills` (Claude Code), `~/.agents/skills` (Codex, official user dir; agy and Codex confirm symlinked skill dirs are followed), `~/.gemini/skills` (Antigravity; its `antigravity*/skills` dirs link there). A skills dir is created when its agent root (`~/.claude`, `~/.codex`, `~/.gemini`) exists (Codex); absent agents are skipped.
- Links are absolute, resolved from the module's own location, not cwd (agy, Codex). Idempotent: a correct link is left alone; any other file, dir or foreign symlink is a reported conflict and is never overwritten (Codex). `--uninstall` removes only links that point into this checkout (agy). A bin dir missing from PATH prints a warning (agy, Codex).

Why: symlinks keep every machine on the checkout's current skill and toolchain after a `git pull`, with no copy to update; a command reuses the toolchain's Python and is testable.

Revisit when: an agent stops following symlinked skill dirs, an agent moves its skills dir, or LM gets a packaged install (pip, Homebrew).
