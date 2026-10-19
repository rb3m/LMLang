# ADR-015 Function values are pure and total (M1)

`Fn` types carry no effect or failure sets; lambdas and named functions used as values must be pure and total. Why: keeps the type language tiny and the checker local; higher-order stdlib (`map/filter/fold`) stays sound without effect polymorphism. Revisit: if benchmark tasks need effectful callbacks (then add `(Fn (..) R eff)` or a separate `each` form).
