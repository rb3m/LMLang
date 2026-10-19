# LM guide

## Workflow
1. Start with `lm index` (`--stdlib --modules`, then `--module M` for stdlib); `lm slice MOD.FN` before files.
2. Change code with `lm edit` ops (see `lm help edit`) rather than rewriting files.
3. Loop `lm check` -> `lm test` until clean.
4. JSON diagnostics give a code, node path and often a `fix` for `lm edit apply`.
5. Propose scenarios in `tests/accept/*.accept`; show `lm accept --review`.
6. Only after explicit human yes: `lm accept --approve DIGEST --by "<their words>"`; never `--bless`.
7. `lm accept --guard` must pass at the end.

Stdlib: `lm index --stdlib`.

```
(module billing
  (purpose "Invoice totals.")            ; one line <= 100 chars; required
  (use list)                             ; modules referenced; always used qualified: list.map
  (export total)                         ; optional: absent = export all, (export) = export nothing
  (type Cents Int)                       ; alias | (rec (f T)..) | (sum (V (f T)..) Bare ..)
  (error BadRegion (region Str))
  (fn total
    (purpose "Sum item prices and add tax.")
    (sig (items (List Cents)) (region Str) -> Cents)
    (eff)  (fails BadRegion)             ; omitted = pure / cannot fail
    (requires (> (len items) 0))
    (ensures (>= result 0))
    (example ((list 100 200) "MX") => 348)   ; or => (fail BadRegion "XX")
    (body (if (= region "MX") (let ((s (list.sum items))) (+ s (/ (* s 16) 100))) (fail BadRegion region)))))
```
(Zero-parameter fn: `(sig -> Int)`. Own names bare; others `mod.name`. No shadowing. Fn values (lambdas, `list.map` callbacks) must be pure and total.)
External constants (`lm run`/scenarios): qualify module names, e.g. `(shapes.Circle 2)`; prelude stays bare.
Generic types bind distinct, used single letters: `(type (Tree a) (sum Leaf (Node (left (Tree a)) (value a) (right (Tree a)))))`; use `(Tree Int)`; `(export Tree)` exports type and variants. Constructors infer fresh arguments; records use `(type (Box a) (rec (item a)))` and `(new Box (item 1))`. Aliases may take parameters too. Recursion preserves parameter order; aliases cannot be recursive. Map/Set key requirements propagate through fields and aliases.
Constants: `(const moon-gravity (purpose "Lunar surface gravity.") (type Float) (value 1.62))`; bare in own module, qualified elsewhere; evaluated at check time under a 1,000,000-step budget.

Expressions: literals (Str escapes: `\" \\ \n \t \u{..}`), `x`, `mod.x`, `(f a)`, `(if c a b)`, `(let ((x e)) b)`, `(let? ((x opt-e)..) b)` (each `opt-e` is `(Opt T)`, `x` gets the payload; the first None skips the rest and gives None; `b` is `(Opt R)`; replaces `match` pyramids over Opt), `(do e1 .. en)` (`e1`..`e(n-1)` Unit), `(for (x xs) b)` (`xs` List evaluated once; `x` bound per element; `b` Unit, returns Unit), `(match e (pat b)..)` exhaustive (pats include `(list p..)`, `(cons h t)`, `(pair p q)`), `(lam ((x T)..) b)` / `(lam (x..) b)` (inferred types: all typed or all untyped), `(list ..)`, `(mapof (k v)..)` `(setof k..)` (keys: Int/Float/Str/Bool literals, no duplicates; `(mapof)` empty), `(new T (f e)..)`, `(get r f)`, `(with r (f e)..)`, `(and ..)`, `(or ..)`, `(fail E ..)`, `(try e (catch E (x..) h))`, `(note "..")`.
Prelude (only unqualified names): `+ - * / mod = != < <= > >= not len cons pair Some None DivZero OutOfRange`. Everything else is qualified and needs `(use ..)`. Type `(Pair a b)`: `(pair a b)` value, `pair.first pair.second pair.swap` (more than two fields: use a record; Pair cannot be a Map key or Set element). Types `(Map K V)`/`(Set K)`: K is Int, Float, Str or Bool (or a sig type var used as a key); immutable, `=` structural, every traversal and print in ascending key order. `map.put at has remove size keys values fold update to-list from-list` (`at` -> Opt; `get` is reserved; `to-list` ascending pairs, `from-list` last-wins), `set.add has remove size to-list from-list fold union intersect diff`. Opt/list/str helpers: `opt.unwrap-or opt.map opt.is-some`, `list.head list.tail list.last` (Opt), `list.zip` (equal lengths), `list.at` (Opt; `nth` fails OutOfRange unless proven safe) `list.take list.drop list.sort-by`, `str.index-of str.replace str.repeat str.pad-left str.pad-right str.upper str.lower str.upper-ascii str.lower-ascii str.to-codes str.from-codes (str.BadCode)` (full list: `index --stdlib`). JSON: `json.Json` (7 variants), `json.parse json.print json.field`. Output: `io.print`/`io.eprint` write a line to stdout/stderr (eff `io.out`); `io.args`, `io.read-line`, `io.read-all` use `io.in`. Effects set: `io.out io.in env.read fs.read fs.write fs.delete net.http proc.run time.now rand`; `time.now-ms time.mono-ms` use `time.now`, `rand.int rand.float` use `rand`.
`pat`: `compile(Str) -> Pat` (fails `BadPattern`; literals proven safe), subject-first `matches find find-all split replace-all replace-with`; scalar offsets/captures, leftmost-first; opaque `<pat>` (SPEC 8).
Vec: `(Vec a)`, `(vecof e..)`, `vec.empty from-list to-list size at set push pop last fold map repeat tabulate nth put`; persistent trie; proofs use `(vec.size NAME)`; `len`/`for` stay List-only.
`env.lookup(name) -> (Opt Str)` reads the environment (eff `env.read`, total; invalid names give None). Files: `fs.read exists entries is-dir` use `fs.read`; `fs.write append make-dir` use `fs.write`; `fs.remove` uses `fs.delete`; `fs.rename` requires both `fs.write` and `fs.delete`. All fs functions fail `fs.IoError`.
`http.request(method,url,headers,body)` / `http.fetch(url)` -> `http.Response`, eff `net.http`, fails `http.HttpError`. Verified HTTPS; HTTP loopback-only; fixed limits, no redirects/proxies or network examples (SPEC 8).
`proc.run(argv,stdin,cwd,env) -> Result`, eff `proc.run`, fails `ProcError`; absolute executable, exact env, POSIX; `proc.which(name,dirs)` uses `fs.read`; `given proc` scripts (SPEC 5/8).
Effectful examples require `given`: `(example () (given (stdin "hi")) => unit (out "hi\n"))` for `io.in io.out`. Inputs: `args stdin env file dir now-ms seed proc`; checks: `out err file no-file dir no-dir` (SPEC 5/12). Fresh fake world, clocks 0, seed 0. Omitted out/err assert empty; checks run after expected failures.
Case matters: values lowercase-kebab; Types/Variants/Errors Capitalized. No comments, no mutation. Int is signed 64-bit (`math.int-min`/`math.int-max`); overflow is the uncatchable fault E-OVERFLOW, never declared in `fails`; Int `/` and `mod` fail DivZero unless divisor is nonzero literal or proven safe; violating a discharged op under `--no-contracts` is uncatchable fault E-PROOF-VIOLATED. Float is finite binary64: literals need `.` or an exponent (`1.0`, `2.5e-3`), print as Python repr (`100.0`, `1e-05`, `1e+16`); `+ - * / < <= > >=` take Int or Float pairs, never mixed (convert with `float.from-int`, `float.round`/`trunc`/`floor`/`ceil` -> Int); a NaN/infinite result (e.g. Float `/` by 0.0, which never fails DivZero) is the uncatchable fault E-FLOAT; no Float literals in `match` patterns. `float.pi`/`e` are zero-parameter constants; `float.exp ln log2 log10 pow cbrt hypot sin cos tan asin acos atan atan2` are deterministic (error <= 1 ulp); logarithms require x > 0.0, exponential overflow faults E-FLOAT, underflow is allowed; `pow` rejects zero with a negative exponent and negative bases with non-integer exponents; `pow(x, 0.0)` is 1.0; `cbrt` accepts negative inputs; `hypot` avoids intermediate overflow; `sin cos tan` accept every finite binary64 angle in radians and return finite results; `sin((float.pi))` is `1.2246467991473532e-16`; `asin acos atan atan2(y,x)` return radians (`asin acos`: |x| <= 1; `atan2(0,0)` = 0); `float.log1p`/`expm1` preserve tiny x in ln(1+x)/exp(x)-1 (`log1p`: x > -1); `float.sinh cosh tanh` are hyperbolic (sinh/cosh overflow faults, tanh is always finite); `float.sqrt` is correctly rounded.

`float.fixed(x, digits) -> Str` requires digits 0..17: exact binary value rounded ties-to-even, fixed decimal places, no exponent or minus on rounded zero; `float.round` rounds halves away from zero.
`date` is pure Gregorian years 1..9999: `Date`/UTC `DateTime`, `valid make parse print to-days from-days add-days diff-days weekday compare`, `valid-datetime make-datetime parse-datetime print-datetime from-epoch-ms to-epoch-ms compare-datetime`; strict `YYYY-MM-DD` / `YYYY-MM-DDTHH:MM:SS.mmmZ`, Opt for invalid/out-of-range input; durations are Int, `date.ms-per-day` = 86400000; now: `(date.from-epoch-ms (time.now-ms))`.

## Scenario file format

Each scenario file contains one `(scenarios ...)` form. Names are unique.

```lisp
(scenarios
  (scenario "Order with tax"
    (status proposed)
    (why "A Mexican order of 100 and 200 cents totals 348 with 16% VAT.")
    (run billing.total (list 100 200) "MX")
    (expect 348)))
```

After the qualified target: separate constants matching its signature. Qualify module names in nested values and `new`; prelude stays bare.

Use exactly one of `(expect VALUE)`, `(expect-fail billing.BadRegion "US")`, or `(expect-out "text")`. For output expectations, add `(allow io.out)` before `run`. Keep scenarios proposed until owner approval (Workflow).

Allow every declared effect, even on unused paths, with separate clauses: `(allow io.out) (allow fs.read)`.
