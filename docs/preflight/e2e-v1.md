# e2e v1 smoke (2026-10-01)

Five live turns via `harness/scripts/smoke_session.py` against harness (wake disabled), Jev, LLM, Muse (100.122.149.75:8080), proxy (127.0.0.1:8765). All five turns completed with `turn_end`; no errors.

Observations: "tell me a joke" was labelled `wrong` by the spoken correction on turn 5 (expected: correction flow works). "pause the music" returned 3.49 MB audio in 0.35 s (likely ack/buffered audio; not investigated).

## Turns

| utterance | wall s | audio bytes | text/error frames |
|---|---|---|---|
| play something chill | 10.20 | 511800 |  |
| what's playing | 1.66 | 538140 |  |
| pause the music | 0.35 | 3491504 |  |
| tell me a joke | 4.72 | 756408 |  |
| no, I meant something upbeat | 2.91 | 651040 |  |

## Decision log (last 5)

| text | route | decider | escalation | calls | outcome | latency_ms | labels |
|---|---|---|---|---|---|---|---|
| play something chill | music.play | llm | needs_args | [{"capability": "music.play", "args": {"mood": "chill"}}] | ok | {"jev": 275.7656346075237, "llm": 518.741203006357, "execute": 5886.552978307009, "total": 10127.89207091555} | [] |
| what's playing | music.now_playing | jev | None | [{"capability": "music.now_playing", "args": {}}] | ok | {"jev": 225.41371919214725, "execute": 0.07111765444278717, "total": 1641.438351944089} | [] |
| pause the music | music.control | jev | None | [{"capability": "music.control", "args": {"action": "pause"}}] | ok | {"jev": 316.6223648004234, "execute": 0.043360982090234756, "total": 323.48521798849106} | [] |
| tell me a joke | chat | llm | chat | [] | reply | {"jev": 217.0584020204842, "llm": 947.5335408933461, "execute": 0.004770699888467789, "total": 4715.014177840203} | [{"id": 1, "decision_id": 4, "at": 1790866166.144466, "label": "wrong", "source": "spoken_correction", "corrected_by": 5}] |
| no, I meant something upbeat | music.play | llm | correction | [{"capability": "music.play", "args": {"mood": "upbeat"}}] | ok | {"jev": 215.4713310301304, "llm": 563.6129630729556, "execute": 222.39112108945847, "total": 2900.532326195389} | [] |
