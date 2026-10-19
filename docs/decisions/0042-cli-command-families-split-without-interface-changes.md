# ADR-042 CLI command families split without interface changes (2026-10-16)

`cli.py` now owns dispatch and the existing toolchain-exception boundary. Cohesive modules own project commands, symbol queries, edits, function execution, and acceptance scenarios; `cli_common.py` owns existing shared flag parsing, loading and reporting. Command bodies are moved intact, preserving argument handling, output, exit codes and default project discovery. This restores the module-size guideline without changing the SPEC command interfaces.
