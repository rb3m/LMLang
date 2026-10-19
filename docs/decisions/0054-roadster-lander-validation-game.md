# ADR-054 Roadster Lander: backlog 11 reskinned as a flying-car parking game (2026-10-17, agent consensus)

Context: backlog 11 asked for a Lunar Lander in the style of the 1969 game (Storer's LUNAR) as a real-program test of Floats, `let?`, interactive input and native binaries. The owner reskinned it: a generic flying roadster (no real brand) lands vertically in parking spots. Owner decisions: vertical only (no steering); several parking-spot levels; humorous parking-themed grades on the classic scale; difficulty = gravity (Moon 1.62 easy, Mars 3.71 medium, Earth 9.81 hard, m/s^2); SI units; name "Roadster Lander"; written in LM in its own folder.

Options considered: (a) constant-thrust acceleration (simple, loses the classic fuel/mass trade-off); (b) rocket equation with sub-stepped numeric integration (agy; avoids a missing `ln`); (c) rocket equation in closed form (Codex), needing a logarithm the stdlib lacks; (d) as (c), computing the logarithm with a power series inside the game, as the 1969 program itself did (Claude).

Decision:
1. Location: `games/roadster-lander/`, a self-contained project scaffolded by `lm new` (own `src/`, `tests/accept/`, `accept.lock`). Run the toolchain from that folder; the repo-root gate does not include it.
2. Physics (d): 10 s turns; state is time, altitude, downward speed, fuel; mass = dry mass + fuel; burn rate 0..max kg/s, identical across gravities, and full burn beats Earth gravity at full tank. Closed-form rocket equations with -ln(1-x) as a series summed to Float precision; a turn is split at fuel exhaustion (ballistic after). Touchdown time inside a turn by bisection, split at the speed extremum so a descend-then-rise cannot skip contact.
3. Levels and gravity are independent parameters (Codex, agy). Starting numbers are tuned so all 9 level x gravity combinations are landable perfectly by an autopilot (a pure function with examples) and crash with no burn; target 10-20 turns for a careful player.
4. Grades by impact speed, inclusive upper bounds 1, 3, 7, 15, 30 m/s, above 30 a crater (Codex thresholds, agy's style of messages).
5. Input: numbered menus for level and gravity; malformed or impossible burns re-prompt without advancing time (as the original said "NOT POSSIBLE"); EOF exits cleanly (Codex; agy proposed zero burn).
6. Pure modules for physics, grading and levels; a thin I/O main. Contracts: fuel never negative, fuel never increases. Scenario-facing functions take only Int/Float/Str/List arguments (sidesteps backlog 12).

Who agreed: Codex and agy on rocket dynamics, independent gravity, re-prompting, pure/IO split and contracts; Claude chose (d) over (b) and (c) to keep the classic model without a toolchain change.

Evidence to record: the missing `float.ln`/`exp` (a backlog candidate if another program needs them), check/test iterations per module, and native build size and speed.

Update 2026-10-18 (owner request): `minus-log` is now `(- 0.0 (float.log1p (- 0.0 x)))` (ADR-057), replacing the in-game series with no change in results (all examples and the 8 approved scenarios match the series bit for bit); a brief `float.ln (1 - x)` version cost up to 2e-13 m/s from rounding 1 - x, which motivated `float.log1p`. The lift integral keeps its series, which a closed form would cancel catastrophically.
