# Implementation and verification report

The LM implementation is in `src/wordfreq.lm`. Pure functions handle ASCII tokenization, counting, ordering, formatting, and N validation. Every pure function has examples. Only the entry point, argument dispatcher, and file reader have effects.

From this directory:

```
lm check
lm test
lm accept --review
lm accept --guard
lm run wordfreq.main --allow io.in --allow io.out --allow fs.read -- sample.txt
lm build wordfreq.main -o wordfreq
./wordfreq sample.txt
python3 verify_cli.py
```

Expected sample output:

```
4 the
2 cat
1 and
1 end
1 hat
1 sat
```

`lm run` prints those lines followed by `0`, the returned Int. The compiled executable prints only the requested lines.

## Check/test cycles

There is one project module, `wordfreq`. It passed its first explicit `lm check` / `lm test` cycle (26 examples, zero warnings). Two further cycles after enhancements also passed: 26 examples after extracting the argument dispatcher, then 32 after supporting arbitrarily large positive decimal limits. Total: three explicit cycles, none failing. The implicit checks performed by `lm edit` are separate; they reported temporary unused-import warnings during incremental construction, subsequently removed.

Final results: `lm check`: one module, zero errors, zero warnings. `lm test`: 32 examples, zero failures, zero pure functions without examples. `lm accept --guard`: OK. All 13 proposed scenarios match in `lm accept --review`. No scenarios were approved, no approval lock was edited, and no bless command was run.

The native executable passed 18 integration cases checking exact stdout, empty stderr, and actual process exit status. Cases cover the sample, N truncation, absent FILE, missing file, invalid N values, leading zeroes, huge limits, empty input, ASCII/Unicode separators, and the default ten-word cutoff.

## Every documentation command run

Each was run once, after `lm new wordfreq`:

1. `lm guide`
2. `lm index`
3. `lm index --stdlib`
4. `lm help edit`
5. `lm slice wordfreq.main`
6. `lm slice wordfreq.greeting`
7. `lm slice wordfreq.greet-all`
8. `lm help accept`
9. `lm help run`
10. `lm help build`

The first four were launched together, so their precise completion order is immaterial. No external language documentation or source checkout was consulted.

## Errors, quirks, and guesses

- One `lm edit add-decl` was rejected with E-PARSE, `unterminated string`: my Python string had introduced literal newlines inside an LM string. Retried with escaped `\n`; no toolchain crash.
- Adding imports before their users produces W-USE-UNUSED warnings on intermediate edits. Final warnings are zero.
- I initially guessed `(allow io.out fs.read)` for scenario permissions. Review rejected it as an unexpected or duplicate clause. The supported syntax is separate `(allow io.out)` and `(allow fs.read)` clauses.
- Scenario permission checks require every effect declared on the target function, even for an argument path that performs no file read. I added fs.read permission to the missing-FILE and invalid-N scenarios.
- `lm check`, `lm test`, and `lm accept --guard` all succeeded even when proposed scenarios had invalid permission clauses. `lm accept --review` exposed those problems. All were fixed and the review rerun successfully.
- `lm run` prints the returned Int as an extra line and itself exits zero when main returns 2. My initial integration assertion failed on the extra `0` after the sample output. `lm help run` does not explain either behavior. I used `lm build` and checked the actual executable's statuses 0, 1, and 2. No documented interpreter switch to suppress the returned value was found in that help output.
- Input interpretation chosen where unspecified: N is a nonempty sequence of ASCII decimal digits with positive value; leading zeroes are accepted, while signs (including `+`), whitespace, fractions, and extra arguments are rejected with the N error. Errors go to stdout because the request did not specify a stream.
- LM Int is signed 64-bit. Rather than reject a mathematically positive N that exceeds its range, decimal accumulation saturates at 9223372036854775807. This preserves the effective top-N result for any representable list length.
- File reading uses the documented UTF-8 `fs.read`; its declared IoError is caught and converted to the requested path-specific message.

## Proposed scenarios for human review

All remain `(status proposed)` in `tests/accept/wordfreq.accept`:

| Scenario | Behavior to approve |
| --- | --- |
| ASCII words and separators | ASCII letters/digits form maximal runs; Unicode and punctuation separate; ASCII case folds. |
| Frequency order and limit | Descending counts, ascending words for ties, then top N. |
| Sample frequencies | The supplied text produces the six expected frequency entries. |
| Empty input | Text without ASCII words produces no lines. |
| Default limit | Omitted N selects ten. |
| Invalid limit | Zero is rejected. |
| Missing FILE output | Exact usage line. |
| Missing FILE status | Exit status 2. |
| Invalid N output | Exact positive-integer error line. |
| Invalid N status | Exit status 2. |
| Unreadable FILE output | Exact read error including the supplied path. |
| Unreadable FILE status | Exit status 1. |
| Read sample with default N | Actual file reading produces exactly the six sample lines. |

Run `lm accept --review` to inspect each case and its current match. Approval is left entirely to the human as requested.
