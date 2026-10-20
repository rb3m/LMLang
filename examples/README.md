# LM examples

Working programs to copy patterns from. Each one passes `lm check` and `lm test`. Read `lm guide` first, then open the example closest to your task.

| File | What it shows | Try it |
|---|---|---|
| `billing.lm` | One pure function: contracts (`requires`, `ensures`), examples, a declared error. | `lm test examples/billing.lm` |
| `shapes.lm` | Sum types with `match`, floats, `math` and `str`. | `lm test examples/shapes.lm` |
| `tree.lm` | A generic recursive type `(Tree a)` with higher-order traversals. | `lm test examples/tree.lm` |
| `file-lines.lm` | A small CLI: program arguments, reading a file, effects, exit status. | `lm run file-lines.main --allow io.in --allow io.out --allow fs.read -- FILE` |
| `colsum.lm` | A CSV tool: parse lines, group into a `Map`, print sorted output, handle errors. | `lm run colsum.main --allow io.in --allow io.out --allow fs.read -- FILE 0 1` |
| `cgi-echo.lm` | An HTTP handler for `lm serve` / `lm build --serve` (CGI or listener), JSON output. | `REQUEST_METHOD=GET REQUEST_URI='/hi?a=1' QUERY_STRING='a=1' lm serve cgi-echo.handle examples/cgi-echo.lm --cgi`; deploying: `docs/DEPLOY-CGI.md` |

Larger programs (each has its own `src/` and `tests/accept/`; run `lm` commands inside the directory):

- `../benchprojects/wordfreq/`: one-module CLI that counts words and prints the most frequent ones.
- `../benchprojects/ledger/`: multi-module personal-finance CLI (CSV parsing, budgets, reports).
- `../games/roadster-lander/`: multi-module interactive terminal game (input loop, physics, levels).

To start your own program, don't edit these. Run `lm new NAME` in your own directory and follow the `AGENTS.md` it creates.
