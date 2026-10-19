# ADR-004 Text is storage, AST is semantics, no comments

One canonical printed form; prose lives in `purpose`/`note` AST nodes so printing is lossless. Content-addressed store (Unison-style) deferred until the language semantics settle. Why: gets 80% of the benefit (stable diffs, edit ops, hashes) with plain files git and humans already handle. Revisit: after M6.
