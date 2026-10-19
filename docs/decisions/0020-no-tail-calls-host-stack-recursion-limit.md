# ADR-020 No tail calls, host-stack recursion limit (M2)

Deep recursion runs in a 512MB-stack thread; exceeding the limit is a diagnostic (E-RECURSION-LIMIT), not a crash. Revisit: when a benchmark task needs loops over >10k items (then add TCO or a bounded `loop` form).
