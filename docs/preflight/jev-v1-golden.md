# Jev v1 golden replay

Items replayed: 60/60

Overall route accuracy: 100.0% (60/60)

## Per-route accuracy (by expected first route)

| route | accuracy |
|---|---|
| chat | 100.0% (19/19) |
| correction | 100.0% (3/3) |
| music.control | 100.0% (9/9) |
| music.now_playing | 100.0% (3/3) |
| music.play | 100.0% (17/17) |
| music.rate | 100.0% (5/5) |
| speaker.volume | 100.0% (4/4) |

Closed-arg accuracy: 100.0% (16/16)

Latency ms: p50 243, p95 339

## Confidence thresholds

| conf >= | route accuracy of kept | kept | escalated |
|---|---|---|---|
| 0.3 | 100.0% (60/60) | 60 | 0.0% |
| 0.5 | 100.0% (58/58) | 58 | 3.3% |
| 0.7 | 100.0% (51/51) | 51 | 15.0% |
| 0.9 | 100.0% (45/45) | 45 | 25.0% |

## Misrouted

| id | utterance | expected | got | conf |
|---|---|---|---|---|

## Recommendation

Jev routed all 60 golden items correctly and every closed arg (16/16) was right, so no confidence threshold was needed to protect accuracy on this set; it only costs escalations (3.3% at 0.5, 15% at 0.7, 25% at 0.9). Keep `CONF_MIN = 0.5` (escalates 2 items, no accuracy cost here) and keep `JEV_CLOSED_ARGS = True` (no measured accuracy loss, avoids an LLM escalation for closed-arg routes). Caveat: the set is 60 items and was a ceiling result, so it cannot discriminate thresholds; low-confidence behaviour on harder real utterances is unmeasured. p95 latency 339 ms is well under the 1.5 s `JEV_TIMEOUT_S`.
