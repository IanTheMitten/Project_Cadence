# Jev v1 golden replay

Items replayed: 70/70

Overall route accuracy: 98.6% (69/70)

## Per-route accuracy (by expected first route)

| route | accuracy |
|---|---|
| chat | 95.0% (19/20) |
| correction | 100.0% (3/3) |
| music.control | 100.0% (10/10) |
| music.now_playing | 100.0% (3/3) |
| music.play | 100.0% (17/17) |
| music.rate | 100.0% (5/5) |
| schedule.add | 100.0% (5/5) |
| schedule.cancel | 100.0% (3/3) |
| speaker.volume | 100.0% (4/4) |

Closed-arg accuracy: 100.0% (16/16)

Latency ms: p50 214, p95 303

## Confidence thresholds

| conf >= | route accuracy of kept | kept | escalated |
|---|---|---|---|
| 0.3 | 98.6% (69/70) | 70 | 0.0% |
| 0.5 | 98.5% (67/68) | 68 | 2.9% |
| 0.7 | 98.4% (61/62) | 62 | 11.4% |
| 0.9 | 98.1% (51/52) | 52 | 25.7% |

## Misrouted

| id | utterance | expected | got | conf |
|---|---|---|---|---|
| c6 | set an alarm for 7am | chat | schedule.add | 1.0 |

## Recommendation

RECOMMENDATION_PLACEHOLDER

## Schedule items (2026-11-09)

- Previous overall accuracy: 100.0% (60/60). New overall: 98.6% (69/70) with s1-s10 added.
- schedule.add: 100.0% (5/5). schedule.cancel: 100.0% (3/3). s9 ("stop the alarm") and s10 ("what time is my alarm") also correct.
- Wrong schedule items: none. The one miss is pre-existing item c6 "set an alarm for 7am" (expected chat, predicted schedule.add, conf 1.0); with the schedule capability in the catalogue, schedule.add is arguably correct, so c6's label is stale.
- Note: the replay script regenerates this file and left the Recommendation as RECOMMENDATION_PLACEHOLDER; the previous prose recommendation (60-item run) was overwritten.
