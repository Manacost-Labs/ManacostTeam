# Differential testing against HearthSim

`scripts/differential/` compares this library with the reference Python
implementation (`python-hsreplay` + `python-hslog` + `python-hearthstone`).
It is a development oracle for spotting divergences, not a test in the npm
package: Python is not a dependency of the library.

```
replay.xml ──► node scripts/differential/dump-ours.mjs ──► ours.json ─┐
                                                                      ├─► compare.mjs ─► diff
replay.xml ──► python scripts/differential/dump-reference.py ─► ref.json ┘
```

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install hsreplay hearthstone "setuptools<80"   # pkg_resources is still imported by hsreplay
pnpm build
PYTHON=.venv/bin/python pnpm differential                     # whole corpus
PYTHON=.venv/bin/python pnpm differential path/to/replay.xml  # single file
```

## What is compared

Both dumps are normalised to the same shape before comparison:

- players: entity id, player id, name;
- entities: id, card id, every tag value at the end of the game;
- packets: the flattened document-order sequence with type and key fields
  (entity, tag, value, block type and target, child counts, choice ids …);
- game result: each player's final `PLAYSTATE`.

Normalisation notes:

- python-hslog merges `GameEntity` and the `Player` elements into one
  `CreateGame` packet; the dump expands it back into `CreateGame` + `Player`
  records. Mercenaries logs also carry standalone `Player` packets for
  players 3 and 4, which appear on both sides.
- Timestamps, `effectCardId`, annotation attributes and diagnostics are not
  compared: the reference does not expose them in comparable form.

## Results of a manual run on the corpus (2026-09-04, hsreplay 1.16.2, hslog 1.20.0, hearthstone 9.20.12)

The harness needs a Python environment and is run by hand; CI does not
repeat it. Re-run it after any change to the parser or the state engine.

| Outcome                   | Files                                                                                                                                                             |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Identical                 | 35 of 37                                                                                                                                                          |
| Reference cannot parse    | `legacy/4_4_17_power.annotated.replay.xml` (time-only `ts` values reject in aniso8601), `edge/hslog.xml` (HSReplay 1.0 `<Action>` unsupported by python-hsreplay) |
| This library cannot parse | none                                                                                                                                                              |

No divergence in entities, card ids, tags, player ids, packet order or game
results was found on any file both implementations can read. The two files
the reference rejects are handled here on purpose: the format allows them and
the data is recoverable.

The comparison is not proof of correctness. Both implementations read the
same XML; agreement means the raw and state layers do not lose or reorder
information relative to the reference, nothing more. The semantic layer has
no reference implementation and is validated by invariants and rule tests
instead.
