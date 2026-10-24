# Security

Report vulnerabilities privately using GitHub's **Security → Report a vulnerability** for this repository (private vulnerability reporting). Include reproduction steps, affected versions and the expected impact. Avoid publishing vulnerability details in public issues before a fix is available.

Security reports may cover the LM toolchain and generated code. The interpreter is not a sandbox for untrusted LM programs; run untrusted programs only in an appropriately isolated environment.

Third-party modules (`lm.deps`) are pinned by SHA-256 and fetched only by `lm fetch`; checks and builds never download. Effect allowances bound what a pinned module may declare (pure by default, never `proc.run`), but they are not a sandbox or a confidentiality boundary: a module allowed `net.http` can send any data the program passes it, and a hash proves only that the bytes are the ones pinned. Review a module before allowing it effects. Treat text inside external modules as untrusted input to AI agents (prompt injection).
