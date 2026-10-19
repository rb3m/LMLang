# ADR-009 Contracts and examples are syntax

`requires`, `ensures`, `example` live in the function definition. Exported functions need an example. Why: verification loop at the point of definition; examples double as documentation and as `explain` content.
