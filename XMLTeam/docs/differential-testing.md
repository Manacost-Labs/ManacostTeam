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
.venv/bin/pip install -r scripts/differential/requirements.txt   # pinned reference versions
pnpm build
PYTHON=.venv/bin/python pnpm differential                          # whole corpus
PYTHON=.venv/bin/python pnpm differential --report-dir out a.xml   # single file + report artifacts
```

Reference versions are pinned in `scripts/differential/requirements.txt`
(`hsreplay==1.16.2`, `hslog==1.20.0`, `hearthstone==9.20.12`); bump them
deliberately and re-run.

## Outcomes

| Outcome                 | Meaning                                                                 | CI                                                                                                  |
| ----------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `MATCH`                 | both sides agree on players, entities, tags, packet sequence and result | pass                                                                                                |
| `DIVERGENCE`            | both parse, results differ                                              | **fail**                                                                                            |
| `OUR_FAILURE`           | this library cannot parse the file                                      | **fail**                                                                                            |
| `REFERENCE_UNSUPPORTED` | the reference raises before producing a document                        | **fail**, unless the manifest entry lists `REFERENCE_UNSUPPORTED` in `knownAnomalies` (allowlisted) |

`compare.mjs --report-dir DIR` writes `differential-report.json` and
`differential-report.md`. The workflow `.github/workflows/differential.yml`
runs weekly and on demand and uploads both as the `differential-report`
artifact.

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

## Latest run (2026-09-04, hsreplay 1.16.2, hslog 1.20.0, hearthstone 9.20.12)

| Outcome                             | Files |
| ----------------------------------- | ----: |
| MATCH                               |    94 |
| DIVERGENCE                          |     0 |
| OUR_FAILURE                         |     0 |
| REFERENCE_UNSUPPORTED (allowlisted) |    10 |

The ten allowlisted files: `edge/hslog.xml` (HSReplay 1.0 `<Action>`, unknown
to python-hsreplay), `legacy/4_4_17_power.annotated.replay.xml` and the eight
`converted/` files (time-only `ts` values, which aniso8601 rejects even
though python-hsreplay wrote them itself). This library reads all ten.

No divergence in entities, card ids, tags, player ids, packet order or game
results was found on any file both implementations can read. Agreement
means the raw and state layers do not lose or reorder information relative
to the reference; it is not proof of correctness, and the semantic layer has
no reference implementation at all.
