# Jev + Needle + Laya: can "decide, then call the tool" replace one cloud LLM?

Date: 2026-09-30. Machine: Linux, 8 CPU cores, 15 GB RAM, no GPU. All local numbers are CPU-only.
Scripts: `harness/scripts/bench_common.py`, `bench_run.py`, `bench_analyze.py`. Raw logs and `summary.json`: `docs/research/data/`.

## 1. Summary

- The user's facts check out: Jev is TypeSafe AI's model; Needle is Cactus Compute's; Laya is an open Apache-2.0 "Jev-compatible" decision model from Convai Innovations (HF org `convaiinnovations`).
- **Jev was run** in a second pass after the user supplied a TypeSafe API key (first pass had no key). It is hosted-only: no weights, no customer fine-tuning. The 48 utterances are synthetic, written by me; they (plus the small context line) were sent to TypeSafe's third-party API. About 193 API calls in total, sequential, no rate-limit or error responses.
- **Needle 3 and Laya run locally on CPU.** Needle: ~87-101 MB RSS, p50 ~0.48-0.51 s per call. Laya: ~2.1 GB RSS (2.9 GB peak), ~1.0 s per decision on CPU.
- **Zero-shot on my 48-utterance test, the cloud baseline wins clearly** (decision 100 %, tool name 91.7 %, args 83.3 %). Needle alone: decision 43.8 %, name 37.5 %, args 33.3 %. Needle + rewritten descriptions: 64.6 / 54.2 / 43.8 %. Laya -> Needle variants: 25-69 % decision, 25-48 % name.
- The binding constraint is not latency; it is zero-shot accuracy on this tool surface. Both vendors say fine-tuning is where accuracy comes from (sections 2.2 and 2.3). The published evidence for the pairing itself is thin (2.4).
- **Jev as the decision stage is the best first stage I measured:** as a 10-way choice (9 tools + `none`) its decision was 97.9 % (47/48) and its tool name 91.7 % on single-tool items, at p50 207 ms / p95 258 ms including the network. Laya got 97.9 % / 64.6 % at p50 1071 ms on this CPU. End to end, Jev route -> Needle reached 0.563 / 0.542 / 0.521 (decision / name / args) and 0.688 / 0.688 / 0.625 with rewritten descriptions, the best of the local-Needle stacks, but still below the cloud baseline (1.000 / 0.917 / 0.833) and with latency p50 537-623 ms versus cloud 612 ms.
- Laya's first-stage decision ("tool or no tool") was 97.9 % correct (47/48) when asked as a 10-way choice including `none`, but Needle then withheld many of the routed calls under its own confidence floor, and the routing tool-name was right on only 64.6 % of single-tool items.
- A Needle-only stack would already give ~0.5 s and ~100 MB. Laya as decision stage adds ~1 s and ~2 GB on this CPU; Jev adds ~0.2 s and no local memory, but needs the network and a third-party API.
- Every run wrote a per-call log (utterance, context, stage probabilities/confidence, calls, latencies, gold, score). That log shape is a candidate for the finetuning dataset (section 7).

## 2. Per-model facts

### 2.1 Jev (TypeSafe AI)

| Claim | Source |
|---|---|
| Made by TypeSafe AI; "System One" model; typed calibrated answers instead of text; trained with RLCD (Reinforcement Learning for Calibrated Decisions) | https://typesafe.ai/blog/introducing-system-one-models-and-jev |
| Early access, developers brought off a waitlist | same blog, "What's next" section |
| Endpoint `POST https://api.typesafe.ai/v1/systemone`, `Authorization: Bearer`, body `{state, model, questions}`; questions are `choice` (criteria dict -> per-option probabilities + confidence), `score` (ordered criteria list), `noul` (yes/no probability) | https://docs.typesafe.ai/introduction/quickstart |
| Model `jev-1.13.0` (alias `jev-latest`); $0.042 per million input tokens, output free; 64k context (32k for state + longest question); text only; rate limits 100K tok/s, 40 req/s (noted as changing) | https://docs.typesafe.ai/models |
| Same weights serve every account; "not fine-tuned or LoRA-adapted with customer data" | https://docs.typesafe.ai/models |
| Not a drop-in LLM; does not generate text, call tools, or converse | https://docs.typesafe.ai/introduction/coding-agents |
| Known weaknesses: literal reading, numbers/counting, date comparison, indirection, generation | https://docs.typesafe.ai/model-jaggedness/jev-1.13 |
| Jev alone can do function calling: function name and closed-set arguments mapped to Choice questions, each with confidence (cookbook uses 10 typed trading functions, model `jev-1.12`) | https://docs.typesafe.ai/cookbooks/function_calling |
| Documented patterns: intent routing (classify, then route to deterministic code, a specialist LLM or a human; confidence below 0.5 goes to a human) and speculative fan-out (ask many questions in one call) | https://docs.typesafe.ai/patterns/intent-routing ; https://docs.typesafe.ai/demos/smart-home |
| Smart-home demo pairs Jev with an LLM: Jev flags a compound request, an LLM splits it into atomic commands, Jev evaluates each; conversational LLM is the fallback | https://docs.typesafe.ai/demos/smart-home |
| Access for this benchmark: a key supplied by the user (read at runtime from a local file, never stored in this repo or the logs); raw logs contain only utterances and model answers | (user-provided) |
| Parameter count: **not found** in the docs pages I read (blog, models, quickstart, system-one, jaggedness). Weights/licence: no open weights are offered in those pages; access is via the hosted API. | (absence, see section 6) |

Observed in my runs (Jev 1.13.0, from the `model` field in responses): each request of ~93 input tokens plus the 10-option question criteria was billed as ~600 input tokens (`usage.input_tokens`), i.e. the questions count as input; 58,360 input tokens over the 96 `jev_route` calls. The response carries `choice`, `probabilities` and `confidence` per question, as documented.

Jev's own benchmark methodology (blog, "Evidence / Technical Results"): the "workflow evals" use the average of GPT-6 Astra and Fable 5.1 predictions as the reference answer, so the authors themselves state this biases results toward those vendors; the hallucination chart uses LLM numbers from OpenRouter and a non-empirical 0 % for Jev (schema match "guaranteed"); the side-by-side demo uses a short dense state that the authors say flatters Jev. The "193x faster / 445x cheaper" figure quoted by Tom's Hardware is a secondary source and was not checked against a TypeSafe primary page. No smart-home or tool-call accuracy number was found in the primary pages.

### 2.2 Needle 3 (Cactus Compute)

| Claim | Source |
|---|---|
| Built by Cactus Compute; 8-29 MB single file; tool calls, structured extraction, embeddings; Apache-2.0 | https://github.com/cactus-compute/needle ; https://huggingface.co/Cactus-Compute/needle3 (licence in card metadata) |
| 121M parameters at 20 layers (most in an "engram" memory); every depth 2-20 layers is deployable (29-121M); 2.125-bit CQ2 quantisation | https://huggingface.co/Cactus-Compute/needle3 ; https://cactuscompute.com/needle |
| Input: text + tool definitions (JSON schema dicts, OpenAI-style wrappers, Pydantic models or decorated functions); output: one JSON object with `function_calls`, `reasoning`, `confidence`. Empty list for an off-topic request. Byte-level grammar constrains decoding so the JSON is well-formed | https://github.com/cactus-compute/needle ; https://cactuscompute.com/blog/needle-python-docs |
| Confidence = min(calibrated head over prompt+call, decode probability of call tokens); engine withholds calls below 0.1 into `suppressed_calls`; "grounding gates" also withhold calls whose slots are not grounded in the request | https://cactuscompute.com/blog/needle-confidence |
| Runtime: `pip install cactus-needle`, sub-1 MB engine downloaded from HF and cached, CPU; Python API `Needle(tools, system, weights)`, `agent.complete(text)` (one turn) or `agent.run()` (executes tools) | https://cactuscompute.com/blog/needle-python-docs |
| Telemetry on by default (disable with `NEEDLE_TELEMETRY=0`, `DO_NOT_TRACK=1`); I disabled it for all runs | https://github.com/cactus-compute/needle |
| Fine-tuning: local LoRA (rank 16 on attention, JSONL `query`/`tools`/`answers`/`reasoning` per line; confidence head untouched, `confidence` becomes `None`), or hosted platform (full model, every depth, calibrated head, 100-10,000 examples, "3 fine-tuning runs for $19") | https://cactuscompute.com/blog/finetuning-needle ; https://cactuscompute.com/needle |
| Published benchmarks: exact-match tool calling on Mobile Actions (961 rows), DroidCall (200 rows), BFCL v4 single turn; field micro-F1 for extraction. The bar values are in SVG images that I did not extract, so **I cite no Needle score**. Fine-tuned on DroidCall: +18 to +36 points per subnetwork; 4-layer and up passes DeepSeek V4 Flash (vendor claim) | https://cactuscompute.com/needle ; https://github.com/cactus-compute/needle |
| Speed claim: 400-4k tok/s decode, 1-10k tok/s prefill (their hardware, unspecified on the page I read) | https://cactuscompute.com/needle |
| Needle 2 (previous gen): 45M params, 14 MB, 28 MB RAM session | https://huggingface.co/Cactus-Compute/needle2 |

### 2.3 Laya (Convai Innovations)

| Claim | Source |
|---|---|
| Open-weight, non-autoregressive System-1 decision model; Apache-2.0; same input/output contract as Jev (`state` + typed `questions` -> `answers` with probabilities) | https://huggingface.co/convaiinnovations/laya |
| Checkpoints: English 421M (ModernBERT-large, 512 ctx); multilingual 322M (mmBERT-base, 1024 ctx, up to 8k); typed-decisions fine-tune 421M (1024 ctx) | https://huggingface.co/convaiinnovations/laya |
| `pip install laya`; `Router().predict(state, questions, model=...)`; optional ONNX, HTTP, MCP extras | https://huggingface.co/convaiinnovations/laya |
| Vendor latency: 39.5 ms (English) / 32.8 ms (multilingual) per question on a Tesla T4 GPU | https://huggingface.co/convaiinnovations/laya |
| Fine-tuning via a Kaggle notebook (RLCD, GRPO-style policy gradient, calibration temperatures). Typed-decisions benchmark: base checkpoints 0.36 / 0.35 (random 0.318), fine-tuned 0.766, vs Jev's "published 0.727". The README says to "treat Laya as a fast base to specialise, not as a zero-shot decision engine" | https://github.com/NandhaKishorM/laya (README "Fine-Tuning") |
| `confidence` for choice/score is 1 - normalised entropy, not Jev's formula; thresholds do not transfer from Jev | same README |
| Third-party-written (not vendor) parity claims against Jev (Laya vs Jev charts in the README) are the authors' own and use their benchmark; not independently checked here | same README |

Laya does not emit tool arguments. It answers choice/score/noul questions only, so on its own it can at most pick a tool name.

### 2.4 Is "Jev + Needle" a documented pattern?

I found **no TypeSafe or Cactus primary page that documents Jev handing off to Needle** (neither vendor's pages I read mention the other). What the primary sources do document:
- TypeSafe: Jev handles decisions/routing in code, and pairs with LLMs for string generation (smart-home demo, intent-routing pattern) and can itself do closed-set function calling (cookbook).
- Cactus: Needle does the tool call on-device and refuses with `[]` for off-topic requests, so it already contains a built-in "is there a tool for this" step, with a calibrated confidence for act/confirm/refuse routing.
Search results also surface a third-party GitHub repo (`Ryan-PG/yt-jev-needle3-laya`) and blog posts comparing the three; I did not treat them as primary and did not read them. The hand-off I built (Laya stage -> Needle with a shortlisted toolset) is therefore my own design derived from TypeSafe's intent-routing pattern, not a vendor-specified integration.

## 3. Benchmark method

- **Tool surface (9 tools):** the 8 Muse tools, schemas read verbatim from `harness/cadence/muse/mcp_server.py`, plus `set_warmth(kelvin 1800-6500, brightness 0-100)`, **a made-up schema** for the circadian light.
- **Test set:** 48 utterances written by me (`bench_common.TESTSET`): music by vibe (5), by text (3), recommend_next (3), play (3), player-state read (3), write (4), dashboard (2), rate (4), light (6), chit-chat/no-tool (8), ambiguous (5), multi-step (3). 40 are unambiguous tool-or-not items. The gold labels are mine and the set is small; one item is ~2 points.
- **Shared context** given to every architecture: `Currently playing: track_rowid 3112. Time 22:30. Lights 4000K brightness 80.` (system prompt for cloud/Needle; included in Laya's `state`).
- **Gold format:** per utterance a list of acceptable outcomes (list of calls, `[]` = no tool), with argument specs as exact values, substring lists or ranges. Only the **first step** is scored for multi-step requests (e.g. "play some jazz" -> `search_vibe`).
- **Metrics:** decision accuracy = "some tool vs none" agrees with an acceptable outcome. Tool-name accuracy = multiset of names equals an acceptable outcome. Argument accuracy = names right and all checked args right. Scored on rep 0 (n=48). Cloud and all local archs also ran extra reps only for latency stats.
- **Runs:** each arch in its own process (memory measured as `VmRSS`/`VmHWM`), sequential, one request at a time. Local archs: 3 reps of 48 (144 calls). Cloud: 2 reps (96 calls). Needle, Laya and Jev outputs were identical across reps (deterministic on the 2-rep Jev run; 0 of 48 items changed); cloud changed on 4 of 48 items between reps.
- **Latency** = wall time of the decision+call path only (Laya predict + Needle complete, plus Needle agent lookup). Cold = first call of the process and `init_s` (model load); warm = all other calls. p95 on 143 samples is stable-ish; cloud has 95.
- **Architectures:**
  - A `cloud`: `gemma4:31b-cloud` through local Ollama (`/api/chat`, tools, `think:false`; same model and endpoint as `harness/cadence/llm.py`). Ollama reported it as served remotely; latency includes the network.
  - B `jev_route`/`jev_gate`/`jev_route_rewrite`: same as the Laya variants but stage 1 is the hosted Jev API (`POST /v1/systemone`, `model: jev-latest` = `jev-1.13.0`), with exactly the same questions (`GATE_Q`, `ROUTE_Q`) and thresholds as Laya. Reps: `jev_route` 2 (96 calls), `jev_gate` 1, `jev_route_rewrite` 1. Sequential single-threaded calls; the run is coded to stop on any 4xx/429/529 instead of retrying (none occurred). Latency includes the internet round trip from this machine.
  - C1 `laya_gate`: Laya noul "does the user ask the device to do something?" (threshold 0.5) -> Needle with all 9 tools.
  - C2 `laya_route`: Laya choice over the 9 tool names + `none`; shortlist = tools with p >= 0.25 (max 2), argmax `none` stops -> Needle with only the shortlist. `*_rewrite` = same with the tool descriptions rewritten in user phrasing per Cactus's tool-design guide (`bench_common.REWRITE`, written by me).
  - D `needle`: Needle alone, all 9 tools, Muse descriptions as shipped. `needle_rewrite`: rewritten descriptions.
  - E Laya stage 1 alone = C2's first stage (decision and tool name only, no arguments).
- **Needle call handling:** `function_calls` only count as emitted. The `+suppressed` rows post-hoc count calls Needle withheld under its 0.1 floor (what a "confirm band" UI would show); computed from the logs, not re-run.
- Zero-shot only. No fine-tuning was done for any model. Laya ran its English checkpoint via `laya` 0.3.x; a runtime warning said the checkpoint ships an out-of-range calibration temperature, so its confidences are flagged as uncalibrated by the library itself.

## 4. Results (n = 48 utterances, rep 0 for accuracy)

| Architecture | Decision acc | Tool-name acc | Arg acc | Chat false-positive | Miss on tool items | Latency p50 / p95 warm (ms) | First call (ms) | Load (s) | RSS after load / peak (MB) |
|---|---|---|---|---|---|---|---|---|---|
| A cloud gemma4:31b-cloud | 1.000 | 0.917 | 0.833 | 0/8 | 0 % | 612 / 1236 | 635 | 0.09 | 30 / 46 (client only) |
| B1 Jev gate -> Needle (Muse desc.) | 0.479 | 0.396 | 0.354 | 0/8 | 64.1 % | 549 / 953 | 562 | 3.0 | 98 / 105 (client + Needle) |
| B2 Jev route -> Needle (Muse desc.) | 0.563 | 0.542 | 0.521 | 0/8 | 53.8 % | 537 / 1279 | 865 | 2.2 | 98 / 105 |
| B2 Jev route -> Needle (rewritten desc.) | 0.688 | 0.688 | 0.625 | 0/8 | 38.5 % | 623 / 1316 | 814 | 3.3 | 99 / 106 |
| C1 Laya gate -> Needle (Muse desc.) | 0.250 | 0.250 | 0.229 | 0/8 | 92.3 % | 698 / 1410 | 553 | 9.2 | 2070 / 2859 |
| C2 Laya route -> Needle (Muse desc.) | 0.542 | 0.354 | 0.354 | 0/8 | 56.4 % | 1768 / 2359 | 1968 | 8.9 | 2070 / 2859 |
| C2 Laya route -> Needle (rewritten desc.) | 0.688 | 0.479 | 0.438 | 0/8 | 38.5 % | 1749 / 2403 | 1746 | 7.1 | 2070 / 2860 |
| D Needle alone (Muse desc.) | 0.438 | 0.375 | 0.333 | 4/8 | 59.0 % | 476 / 904 | 372 | 2.1 | 87 / 101 |
| D Needle alone (rewritten desc.) | 0.646 | 0.542 | 0.438 | 4/8 | 33.3 % | 513 / 995 | 381 | 2.3 | 88 / 101 |
| E1 Laya stage 1 alone (route Q) | 0.979 | 0.646 (single-tool items only, names) | n/a | | | 1071 / 1408 (stage only) | | | same as C |
| E2 Jev stage 1 alone (route Q) | 0.979 | 0.917 (single-tool items only, names) | n/a | | | 207 / 258 (stage only, incl. network) | 248 (stage only) | | client only |

Post-hoc, counting Needle's withheld (`suppressed_calls`) calls as emitted:

| Variant | Decision | Name | Arg |
|---|---|---|---|
| Needle alone, Muse desc. | 0.833 | 0.500 | 0.333 |
| Needle alone, rewritten desc. | 0.833 | 0.667 | 0.438 |
| Laya route -> Needle, Muse desc. | 0.854 | 0.562 | 0.458 |
| Laya route -> Needle, rewritten desc. | 0.979 | 0.667 | 0.562 |
| Laya gate -> Needle | 0.396 | 0.292 | 0.229 |
| Jev route -> Needle, Muse desc. | 0.896 | 0.833 | 0.625 |
| Jev route -> Needle, rewritten desc. | 0.958 | 0.917 | 0.771 |
| Jev gate -> Needle | 0.854 | 0.583 | 0.438 |

What stands out:
- Jev is the fastest and most accurate *stage 1*: 207 ms p50 over the network against 1071 ms for Laya on this CPU, and tool-name 0.917 versus 0.646 zero-shot. The Jev noul gate was well separated (mean P(needs tool) 0.82 on tool items, 0.08 on chat items) but at threshold 0.5 still passed only 35.9 % of tool items, so the gate missed 64 % (the noul question under-fires on short commands like "pause the music"; the threshold is my choice and untuned). Both routing variants made 0/8 false calls on chat; one chit-chat item ("I'm bored") routed to `search_vibe` at p=0.56 in `jev_route` alone but Needle then emitted no call.
- Most remaining Jev-stack errors are downstream: Needle withheld or mis-filled the call. Counting withheld calls as emitted, Jev route -> Needle gets decision 0.958 / name 0.917 / args 0.771 with rewritten descriptions, versus cloud 1.000 / 0.917 / 0.833. That variant is the nearest the local stack gets, but it depends on a confirm band for the low-confidence calls and still ships every utterance to TypeSafe.
- Jev's stage 1 cannot carry arguments or multi-tool outputs (single choice), so multi-step items (`a3`, `a5`) and category `state_write` (0/4 name-correct in both Jev runs: Jev routed all four to `set_player_state`, but Needle withheld three calls under its 0.1 floor and returned nothing for "pause the music") stay weak.
- Cloud failures are few and instructive: it filled `rate.rating` with 1 or 5 against an enum of [-1, 1] (4 of the 4 rate items' args fail, tool name right), picked `get_player_state` instead of `set_player_state` for "turn shuffle on"/"pause the music", and added an extra `set_player_state` call to "I'm going to bed". The arg score is strict (enum violation counts).
- Needle zero-shot was hurt by the 0.1 confidence floor (many correct-looking calls sit in `suppressed_calls`), by hallucinated calls on chit-chat (e.g. `get_player_state` for "how are you today", 0.73 confidence), and by digit errors (`track_rowid` 9045 -> 945). Rewriting descriptions improved it by ~21 points of decision accuracy on this set.
- The Laya gate (noul) was badly miscalibrated zero-shot: mean P(needs tool) was 0.33 on tool items and 0.14 on chat items, so a 0.5 threshold let through only 7.7 % of tool items. The Laya 10-way choice did far better (decision 0.979), showing the same model is sensitive to question phrasing.
- Laya's stage latency on CPU (~1.05 s p50 for the route question, 10 criteria, ~93 input tokens) is about 25-30x the vendor's T4 GPU figure. The gate question was faster end-to-end (p50 698 ms) mostly because chat items skip Needle.

## 5. Raw-result caveats

- 48 hand-written items, single author, single pass of labelling. No confidence intervals; differences below ~10 points are noise.
- The gold format favours calls that reach a specific tool; ambiguous items (a1, a2, a6, a7) accept several outcomes, which I chose after seeing the cloud behaviour only at design time, not by fitting to outputs, but the judgement is still mine.
- Arg scoring is strict on enums and substrings; for example a range check on kelvin uses my idea of "warmer".
- Needle was tested through `complete()` with `system=CONTEXT`; `Needle(system=...)` is documented as environment facts. No triggers (regex forcing) were used, which the vendor offers for exactly this case. Using triggers or the `Field` grammar constraints would change results.
- Muse tool descriptions ("returns candidates for you to choose between; it does not pick one") are written for an LLM agent, not Needle's "what the user would say" style; that is partly why `needle_rewrite` does better. The rewrite is my text.
- Cloud latency includes the network to a remote-served model and could vary by time of day; local runs are quiet-machine CPU. RSS for cloud is only the client process.
- Laya on CPU used PyTorch defaults (8 threads). The ONNX path, GPU, or quantisation might cut the ~1 s; not tried.
- I did not test multi-turn, tool results fed back, or the full `agent.run_turn` loop. Multi-step items score only the first call.
- Needle's own `peak_ram_mb` field reported 157.7 MB in a smoke test; the process RSS I report for the bench is 87-101 MB (mmap counting differences); both are ~100-160 MB.

## 6. What could not be verified

- **Jev, what was not measured:** "Jev alone with closed-set function calling" (name plus argument Choice questions as in the TypeSafe cookbook) was not built, so Jev-only tool-name accuracy is stage-1 name accuracy, and no Jev-only argument accuracy exists. jev-1.12 versus jev-1.13, fan-out cost, and different regions/time-of-day network latency were not tested. Only 1-2 reps per Jev variant (192 calls total), so p95 is from 47-95 samples. The Jev run used a key supplied by the user; quota and rate-limit headroom beyond the documented 40 req/s were not probed.
- **Jev parameter count and licence terms:** not found in the pages read. Commercial terms were not read beyond the price table in the models page. Note also Jev gives no fine-tuning of the hosted model, which matters for your "drop the cloud" goal.
- **Needle published benchmark values:** only in images; not extracted. The vendor speed claim's hardware is unstated on the pages I read.
- **Laya vs Jev head-to-head:** the claims are the Laya authors'; not independently reproduced.
- **Vendor latency claims** (Laya 33-40 ms on T4; Needle 400-4k tok/s; Jev "40-200x faster") are not reproduced here; my Laya CPU number is ~25x higher than the T4 figure.
- I did not read the third-party blogs or repo that pair the three models (section 2.4).
- Whether anything here survives a larger or differently labelled test set.

## 7. Open design questions for you

1. **Logging schema.** The bench record is a starting point: `{ts, session/turn id, utterance, context snapshot (playing track, time, light state), decision-stage output (per-option probabilities + confidence + model version), shortlist, tool-stage output (calls, confidence, suppressed calls, reasoning), executed calls + results, latency per stage, outcome signal}`. Do you also want to log the cloud LLM's answer for every turn as a teacher label (shadow mode) before dropping it?
2. **Labelling wrong decisions.** Options: implicit (user repeats/corrects within N seconds, skip/thumbs-down after an action, undo), explicit (a spoken "no, I meant..."), or teacher disagreement (cloud vs local). Which signal do you trust, and is a wrong *no-tool* (miss) as costly as a wrong *call* (e.g. an unwanted pause or light change)?
3. **Confidence policy.** Needle's own confidence floor suppressed many plausible calls; Laya's noul gate was miscalibrated zero-shot. Do you want three bands (act / confirm by voice / refuse-and-ask) as Cactus suggests, and who sets the thresholds (fit them on the logged data)?
4. **Is a separate decision model worth it?** Needle already returns `[]` for off-topic. On this set the extra Laya stage added ~1 s and ~2 GB without better accuracy zero-shot. The case for it is routing beyond tool-vs-chat (e.g. tool / chat / needs-LLM-reasoning / ask-clarifying-question). Is that richer routing part of the product?
5. **Fine-tuning path.** Needle: local LoRA (confidence head lost) versus the paid platform run (keeps a calibrated head, needs your data uploaded). Laya: Kaggle-style RLCD training on GPUs, 4-5 h for ~30k questions per its README. Jev: no fine-tuning offered. Which do you prefer given you want to own the model, and how many labelled turns can you realistically collect (vendor guidance: 100-10,000 examples for Needle)?
6. **Tool design.** Wording the tool descriptions for the small model was worth ~20 points for Needle. The Muse MCP tool set is shaped for an LLM (e.g. `set_player_state` needs a queue and `client_state`; `rate` needs a track id the user does not say). Do you want a thin user-facing tool layer for the on-device model that resolves "this song" from player state in code?
7. **Multi-step.** Needle emits calls in order but does not see results unless you feed them through `complete()`. The Muse flow (search, then choose, then play) needs that loop and a chooser; who picks the track (an LLM, a rule, or a learned ranker)? Your agent currently caps at 3 tool calls.
8. **Hardware.** Needle fits an ESP32-class runtime only in principle (its devices guide lists microcontroller targets; I did not check the ESP32-S3 RAM/flash fit). Laya at ~2 GB RSS needs a host. Is the decision stage meant to run on the desktop harness, a phone, or a home server, and is a GPU available there? Laya on this 8-core CPU is ~1 s.
9. **Language and voice.** Needle warns that confidence is unreliable outside English; Laya's English checkpoint collapses on non-Latin scripts (its own README). Is the assistant English-only? Also ASR errors (digits like track IDs) will stress Needle's argument copying: I observed `9045 -> 945`.
10. **Privacy/telemetry.** Needle ships with anonymous telemetry on (I disabled it). Jev sends every utterance and context line to TypeSafe: the benchmark did that with synthetic utterances only. Real home-device speech (and logged decisions) would go to a third party unless you stay on Laya/Needle; is that acceptable?
11. **Jev versus Laya as the decision stage.** Jev was 5x faster (207 ms vs 1071 ms p50) and 27 points better on tool name zero-shot, but it is closed, not fine-tunable and cloud-hosted, so it cannot be the "drop the cloud" end state. Would you use Jev only as a teacher/labeller (logging its probabilities as soft labels for a fine-tuned Laya/Needle) rather than in the serving path?
12. **Bottleneck moves to the tool model.** With a good decision stage, the remaining errors are in Needle's calls and its confidence floor. Is tuning Needle (LoRA on logged calls) the first priority, before any decision-model work?
