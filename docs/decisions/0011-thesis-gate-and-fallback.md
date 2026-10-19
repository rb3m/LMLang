# ADR-011 Thesis gate and fallback

Milestone M6 measures S1-S6. If the thesis fails (notably S4 or S5), do not expand LM; instead extract the tooling (index, slice, edit ops, structured diagnostics, effect annotations) as a strict subset + toolchain over an existing language (typed Python or Rust). Why: my training distribution favors existing languages; a new language must earn its place with numbers.
