# Roadster Lander

Park a flying roadster on the Moon, Mars, or Earth. Choose a parking spot,
then a world, and enter a burn rate from **0 to 12 kg/s** each turn.
A turn lasts up to **10 seconds** and stops at first ground contact.
Burning fuel slows your fall and can send you rising; the display spells out
the direction. Fuel runs out naturally, even partway through a turn.
Aim for an impact of **1 m/s or less** for perfect parking.

From this directory, play with:

```sh
../../bin/lm run roadster-lander.main --allow io.in --allow io.out
```

End input (Ctrl-D on an empty line) to quit. Invalid selections or burns
prompt again without advancing time.

Build and run a native executable (requires Go):

```sh
../../bin/lm build roadster-lander.main -o roadster-lander
./roadster-lander
```

## Validation

Run the checks from this directory:

```sh
../../bin/lm fmt --check
../../bin/lm check
../../bin/lm test
../../bin/lm accept --guard
```

All acceptance scenarios are proposed for owner review. Each expects readable
text: Earth free fall, fuel exhaustion, first contact before a rebound, grade
boundaries, all nine autopilot landings, all nine unpowered crashes, and a
short scripted Moon landing.

Pure reports share one decimal formatter. Telemetry uses falling/rising;
scripted and interactive games share the exact final report, including impact
speed, fuel, elapsed time, and completed turns. Street lot / Moon with no
burns takes three burns (21.4 seconds); the touchdown display is turn 4.

Try the reports directly:

```sh
../../bin/lm run roadster-lander.play-scripted 1 1 '(list)'
../../bin/lm run roadster-lander.turn-report 490.5 0.0 0.0 0.0 3
../../bin/lm run roadster-autopilot.report-all
../../bin/lm run roadster-autopilot.no-burn-report
```

Physics examples pin full numerical states and logarithm precision, including
the unbounded trajectory that rises after contact and the turn that correctly
stops at its first impact. The reports round SI quantities to one decimal.
