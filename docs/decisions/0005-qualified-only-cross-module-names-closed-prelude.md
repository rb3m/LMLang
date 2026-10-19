# ADR-005 Qualified-only cross-module names, closed prelude

`list.map`, never `map` via import list. Why: a name tells where it lives (no lookup), kills "plausible API" confabulation (unknown qualified name = error with candidate list), greppable, one way to write it. Cost: slightly longer tokens per reference; measured in S5.
