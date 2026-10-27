---
name: lm
description: Write, check, test or build programs in LM (LMLang), the s-expression programming language made for AI agents (.lm files, the `lm` CLI). Use when a task mentions LM or LMLang, involves .lm files, or asks for a program written in LM.
---

# LM

1. Toolchain: `lm --version`. If not found, use `bin/lm` in the LMLang checkout this skill comes from (this file is `<checkout>/skills/lm/SKILL.md`; resolve symlinks), and `<checkout>/bin/lm install` puts it on PATH. Needs Python >= 3.10; Go only for native `lm build`.
2. New program: `lm new NAME` in your working directory, then follow the AGENTS.md it creates. Existing LM project: read its AGENTS.md first.
3. Run `lm guide` once before writing code (syntax, workflow, stdlib); `lm help CMD` for any command. Open the checkout's docs only when the guide is not enough.
4. Loop: `lm edit` ops -> `lm check` -> `lm test` until clean. Diagnostics are JSON; apply their `fix` with `lm edit apply`.
5. Scenarios in `tests/accept/` are the human's spec: propose them, never approve them yourself.
6. Changing the LM toolchain itself, not writing a program in it: read the checkout's AGENTS.md instead.
