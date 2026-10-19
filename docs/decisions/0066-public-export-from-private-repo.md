# ADR-066 Public release: export a scanned tree from the private repo (2026-10-19, owner decisions + agent consensus)

Context: backlog 23. The owner decided (2026-10-19): Apache-2.0 with the copyright in NOTICE under the owner's legal name; the public repo starts from one fresh commit and the private LAN repo keeps its full, unrewritten history; docs say "the owner"; branches `m8` and `m9-app` deleted (nothing lost). Open question for agents: docs/ENVIRONMENT.md holds private machine details that agents here need but that must not be published.

Options: (A) keep ENVIRONMENT.md private and build the public tree with a tracked, scanned export script; (B) generic tracked file plus an untracked local file (lost on other machines); (C) generic tracked file plus a private branch or repo for the details.

Decision: (A). `scripts/export-public.sh DEST` takes `git archive HEAD` (refuses uncommitted tracked changes), drops the exclude list (docs/ENVIRONMENT.md), scans the staging tree and fails closed on emails (allowed: noreply@anthropic.com, *@users.noreply.github.com, das@FreeBSD.ORG as a verbatim third-party copyright), private IPv4, home or volume paths (allowed: /home/runner), private host and user words, and the owner's first name outside NOTICE; then syncs into DEST, which must be empty or a separate git repo, and never commits or pushes. `--scan-only` scans the checkout's tracked files; CI and a unit test run it, so leaks are caught at commit time, not at release. Public docs point to docs/ENVIRONMENT.example.md. The known leaks were removed by hand; the scan is a backstop. Later releases rerun the export into the same public repo, so public history accumulates normally.

Also: LICENSE (official Apache-2.0 text), NOTICE, THIRD_PARTY_NOTICES.md (Go BSD-3, Sun fdlibm/msun, FreeBSD BSD-2, copied verbatim from the source headers) and licenses/UNICODE-LICENSE-V3.txt (official text); public README with an honest status (S5 OPEN); CI on Linux and macOS with Python 3.10 and 3.12 plus Go; CONTRIBUTING.md; SECURITY.md (GitHub private vulnerability reporting); version 0.1.0.

Revisit when: a second private file appears (extend the exclude list) or the public repo becomes the working repo.

Who agreed: agy and Codex (gpt-6.1-sol) chose (A). Codex added the isolated staging directory, fail-closed scanning, the separate public repo with accumulating history, and the point that the scan backs up the hand cleanup rather than replacing it. Implementation by Codex (gpt-6.1-sol), verified by Claude.
