# LMLang

LM is a programming language and toolchain designed for AI agents as the primary authors and readers. Agents have finite context, can invent plausible names, and spend tokens regenerating files. LM provides small dependency-closed slices, exact name resolution, declared contracts and effects, structured JSON diagnostics, and edits expressed as operations.

The research thesis is falsifiable: these choices should let an agent use fewer total tokens and introduce fewer defects than equivalent work in Python. The human judges intent through plain-language acceptance scenarios and explanations; agents write and check the code.

## Example

A word of warning before the code: LM is not meant to be read by humans. Every choice that would make it pleasant for you, like familiar syntax, comments, terse shortcuts and overloading, was traded away for what makes an AI agent cheaper and more accurate: one way to write each thing, every name qualified, effects and failures spelled out in every signature. If it looks verbose and alien, that's working as intended. To borrow from Westworld: it's not for you. Your view into a program is its acceptance scenarios and `lm explain`, in plain language.

This is `examples/billing.lm`, checked with `bin/lm check examples/billing.lm`:

```lisp
(module billing
  (purpose "Invoice totals.")
  (use list)
  (export BadRegion total)
  (type Cents Int)
  (error BadRegion (region Str))
  (fn total
    (purpose "Sum item prices and add Mexican VAT.")
    (sig (items (List Cents)) (region Str) -> Cents)
    (fails BadRegion)
    (requires (> (len items) 0))
    (ensures (>= result 0))
    (example ((list 100 200) "MX") => 348)
    (example ((list 100) "XX") => (fail BadRegion "XX"))
    (body
      (if
        (= region "MX")
        (let ((s (list.sum items))) (+ s (/ (* s 16) 100)))
        (fail BadRegion region)))))
```

## Install

Requires Linux or macOS and Python >= 3.10, with no third-party Python packages. Native builds also need Go >= 1.21.

```sh
git clone https://github.com/rb3m/LMLang.git
mkdir -p ~/.local/bin
ln -s "$PWD/LMLang/bin/lm" ~/.local/bin/lm
export PATH="$HOME/.local/bin:$PATH"
lm --version
```

`LM_PYTHON` selects the Python executable. Go discovery tries `LM_GO` first, then `PATH`, then the usual installation locations; see [the environment example](docs/ENVIRONMENT.example.md).

## Quick start

```sh
lm new my-tool
cd my-tool
lm guide
lm check
lm test
lm build my-tool.main             # default Go target: native binary
./my-tool Ana
lm build my-tool.main --target py # standalone Python script
python3 main.py Ana
```

Cross-build native binaries with `--os darwin --arch arm64` or `--os linux --arch amd64`.

## Your part: approving behavior

Agents propose acceptance scenarios (`tests/accept/*.accept`): a plain-language "why", an input, and the expected result. The project owner is the human who approves behavior in your checkout. You never need to read the code.

```sh
lm accept --review      # proposed scenarios, digests, and current behavior
lm explain my-tool.main # a function described in plain words
```

The agent walks you through each scenario. Only after your explicit yes may it run `lm accept --approve DIGEST.. --by "<your words>"`. Agents never approve on their own judgment or hand-edit `accept.lock`. Humans who prefer the interactive workflow can edit `(status proposed)` to `(status approved)` and run `lm accept --bless` in their own terminal; agents never run `--bless`. `lm accept --guard` detects changes to approved scenarios. See [the approval protocol](docs/TESTING.md).

## Status

Research prototype **v0.10.0**, with a standard-library-only Python reference implementation and Go and Python build targets. The benchmark tests the thesis; its measurements are evidence on this task set, not a claim about all programming work.

| Metric | Target | Recorded result |
|---|---|---|
| S1 slice vs project text | <= 25% median | 4.4% |
| S2 edit operations vs regenerated file | <= 30% median | 10.4% |
| S3 invented names/effects caught before runtime | >= 90% | 42/43 (98%) |
| S4 tasks green within two agent iterations | >= 80% | 13/13 (100%) |
| S5 LM tokens vs equivalent full Python | <= 1.3x | **OPEN**: 1.28x, heuristic tokens |
| S6 approved scenarios pass, guard intact | 100% | 6/6 pass, guard OK |

S5 remains OPEN until the real-tokenizer re-measure, despite the current heuristic ratio of 1.28x versus the 1.3x target (ADR-025, ADR-061). See [the benchmark summary](bench/results/summary.md), [PRD](PRD.md), and [evidence](docs/EVIDENCE.md) for methodology and caveats.

## Contributing and documentation

Start with [AGENTS.md](AGENTS.md) and [CONTRIBUTING.md](CONTRIBUTING.md). [SPEC](docs/SPEC.md) defines the language, [commands](docs/COMMANDS.md) describes the toolchain, and [decisions](docs/decisions/README.md) records the design. See [SECURITY.md](SECURITY.md) for private vulnerability reports.

## License

Apache-2.0; see [LICENSE](LICENSE), [NOTICE](NOTICE), and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for attribution and third-party notices.
