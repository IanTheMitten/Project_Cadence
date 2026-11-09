# Free LLM API providers to replace Gemini as the fallback decider

Date checked: 2026-11-09. Question: which free LLM API can replace Google AI Studio (free tier now 20 requests/day per model) as `LlmDecider`'s backend in `harness/cadence/llm.py`?

## What the client needs (from `harness/cadence/llm.py`)

- One `POST` to an OpenAI-style `/chat/completions` URL, header `Authorization: Bearer <key>`, body `{"model", "messages", "tools"}`. No streaming, one attempt, 60 s timeout.
- `tools` are OpenAI `{"type":"function","function":{name, description, parameters}}` (built by `capability_tools()` in `cadence/deciders/llm.py`). Tool names use `__` in place of `.` (e.g. `light__set`).
- The response is read from `choices[0].message`: `content` plus `tool_calls[].function.{name, arguments}`, with `arguments` a JSON string.
- Hardcoded today: `GOOGLE_URL` (endpoint), key name `GEMINI_API_KEY` (env var, else `~/.config/cadence/typesafe.env`), and model `CADENCE_LLM_MODEL` (default `gemini-3.5-flash`). Only the model is set from the environment, so switching provider needs a small code change (see the last section).
- Prompt size per call: system prompt, a JSON context blob, the rolling history, the user text, and one tool schema per capability. That comes to roughly 1.5-3K input tokens. **Daily token caps (TPD) are the limit that binds first, ahead of RPD.**

## Comparison

"Card" means a payment method is required. "Trains" means the free tier may train on your prompts.

| Provider | Model (origin) | Free limits | Tool calling | OpenAI-compat | Card | Trains on data | Source (checked 2026-11-09) |
|---|---|---|---|---|---|---|---|
| **Groq** | `openai/gpt-oss-120b` (OpenAI, US) | 30 RPM, 1,000 RPD, 8K TPM, 200K TPD | Yes, every Groq model; no parallel calls on gpt-oss | Yes, `https://api.groq.com/openai/v1` | No | Not stated. No retention by default; up to 30-day abuse/debug logs, which you can opt out of; ZDR toggle | https://console.groq.com/docs/rate-limits, https://console.groq.com/docs/tool-use, https://console.groq.com/docs/your-data, https://console.groq.com/docs/openai |
| Groq | `qwen/qwen3.8-27b` (**Alibaba, Chinese**) | 30 RPM, 1K RPD, 8K TPM, 200K TPD | Yes, parallel | Yes | No | as above | same |
| Groq | `llama-3.3-70b-versatile` (Meta), `llama-3.1-8b-instant` (Meta), `meta-models/muse-spark-open` (Meta, preview) | Not in the docs' sample table; the docs say real limits are on the console Limits page | Yes, parallel | Yes | No | as above | https://console.groq.com/docs/models |
| Mistral La Plateforme (free mode, also called "Experiment") | `mistral-small-latest` / `mistral-medium-latest` (Mistral, France) | **Not published officially** ("lowest limits, intended for evaluation and prototyping"; real numbers are on the console Limits page). Third-party trackers report about 1 req/s, 500K TPM, 1B tokens/month per model | Yes, native | Yes, `https://api.mistral.ai/v1` | No (third-party reports say phone verification is needed) | **Yes, by default on the free plan**, opt out under Admin Console > Privacy | https://help.mistral.ai/en/articles/698531-why-am-i-hitting-api-rate-limits-and-how-do-i-increase-them ; training: search summary of help.mistral.ai article 455207 (the page fetched did not show the Experiment wording) ; third-party numbers: https://mintlify.com/cheahjs/free-llm-api-resources/providers/free/mistral-plateforme (now 410), https://benchlm.ai/md/free-tier/mistral.md |
| OpenRouter `:free` models | `google/gemma-4-31b-it:free` (Google), `nvidia/nemotron-3.5-super-vl:free`, `nvidia/nemotron-3-ultra-550b-a55b:free` (NVIDIA) | 20 RPM; **50 RPD** if under $10 of credits ever bought, **1,000 RPD** once $10 has been bought (one time) | Yes, these models list `tools` in `supported_parameters` | Yes, `https://openrouter.ai/api/v1` | Not for 50 RPD; a $10 one-time purchase for 1K RPD | Depends on the provider; free-model training is a separate account setting, and many free endpoints log or train | https://openrouter.ai/docs/api-reference/limits, https://openrouter.ai/api/v1/models, https://openrouter.ai/docs/guides/privacy/logging |
| NVIDIA build.nvidia.com (NIM API) | Llama, Nemotron, Mistral and others | About 40 RPM, no published RPD (forum reports; no official page found) | Model dependent | Yes, `https://integrate.api.nvidia.com/v1` | No | Not found | https://docs.api.nvidia.com/nim/docs/product (free for "prototyping, research, development and testing only"; serving real end users is production and needs a license), https://forums.developer.nvidia.com/t/is-nim-free/369368 |
| Cerebras | `gpt-oss-120b`, `qwen-3.8-27b` (Chinese) | Trial: 5 RPM, 30K uncached TPM, 1M TPH/TPD. **The open free tier ended 2026-07-21**; now a one-time $5 credit that expires in 30 days | Yes, parallel | Yes | **Yes** | Not stated | https://inference-docs.cerebras.ai/support/rate-limits, https://www.cerebras.ai/pricing, https://inference-docs.cerebras.ai/capabilities/tool-use |
| Cloudflare Workers AI | `@cf/openai/gpt-oss-120b`, `@cf/meta/llama-3.3-70b-instruct-fp8-fast`, `@cf/mistralai/mistral-small-3.1-24b-instruct` | 10,000 neurons/day. gpt-oss-120b costs 31,818 neurons per M input and 68,182 per M output tokens, so about **140 calls/day** at 2K in / 100 out | Some models; the catalogue flags them | Partly (an OpenAI-compatible endpoint exists, but tool support per model is unclear) | No | Not checked | https://developers.cloudflare.com/workers-ai/platform/pricing/, https://developers.cloudflare.com/workers-ai/features/function-calling/ |
| SambaNova | Llama-3.3-70B, gpt-oss-120b, gemma-4-31B; also DeepSeek (Chinese) | 20 RPM, **20 RPD**, 200K TPD per model | Yes | Yes | No | Not checked | https://docs.sambanova.ai/docs/en/models/rate-limits.md |
| Cohere (trial key) | Command family (Cohere, Canada) | 20 RPM, **1,000 calls/month** | Yes | Compatibility API exists (not checked) | No | Not checked | https://docs.cohere.com/docs/rate-limits (trial = "evaluation keys") |
| Hugging Face Inference Providers | many | **No free credits for free users**; PRO ($9/mo) gets $2/month | Provider dependent | Yes, `https://router.huggingface.co/v1` | Yes, to buy credits | Provider dependent | https://huggingface.co/docs/inference-providers/pricing |
| Together AI | Llama and others | Official docs give no free tier; third parties report a one-time $5 credit | Yes | Yes | Unclear | Not checked | https://docs.together.ai/docs/rate-limits |
| GitHub Models | n/a | **Retired 2026-07-30** | n/a | n/a | n/a | n/a | https://docs.github.com/en/github-models/use-github-models/prototyping-with-ai-models |

Excluded as Chinese providers: DeepSeek, DashScope, Zhipu, Moonshot, MiniMax, SiliconFlow, Baidu. Chinese-origin models seen on non-Chinese hosts, to avoid: Qwen 3.8 (Groq, Cerebras), MiniMax M2.7 (Groq preview), Kimi K2.7 (Cerebras dedicated), DeepSeek V3.x (SambaNova), and `xingchen-agi/*` and `dots-studio/*` (OpenRouter free).

## Ranked top 3

1. **Groq, `openai/gpt-oss-120b`.** It is the only verified free tier above 500 RPD (1,000) that needs no card, has native OpenAI tool calling, and returns in well under 3 s (about 500 tok/s per the Groq models page). Both the provider and the model are US and non-Chinese. By default Groq does not retain prompts, and you can turn on zero data retention. The free plan has existed since 2024 and the docs still list a Free tab, so it is long-standing, not a promo. Caveats: (a) **the 200K TPD cap means roughly 70-130 calls/day at our prompt size.** That is fine for an escalation-only decider behind Jev, but it is the real ceiling. (b) gpt-oss is a reasoning model; sending `"reasoning_effort": "low"` keeps latency down (optional, one payload key). (c) No parallel tool calls on gpt-oss, which is fine because `MAX_TOOL_CALLS` already caps us. (d) The table on the docs page is labelled a sample, so confirm the account's real limits at console.groq.com/settings/limits. Fallbacks on the same key: `llama-3.3-70b-versatile` (Meta, parallel tools, no reasoning overhead; check its limits in the console) and `meta-models/muse-spark-open` (Meta, preview).
2. **Mistral La Plateforme free mode, `mistral-small-latest`.** Mistral is a European provider with its own non-Chinese models and solid native function calling. The reported quota (about 1 req/s, 1B tokens/month) is far larger than Groq's. It ranks second because its limits are **not published officially**, it **trains on prompts by default** on the free plan (you can opt out in the console), and third parties say it needs phone verification. Use it if Groq's token cap is hit regularly.
3. **OpenRouter, `google/gemma-4-31b-it:free`.** Google's model, which can call tools. You get 1,000 RPD only after a one-time $10 credit purchase; without it, 50 RPD. Latency and availability vary because free endpoints are shared and sometimes rate-limited upstream, and free providers may log or train on prompts. Third because it costs $10 to reach a usable quota and has the weakest privacy.

Not recommended: Cerebras (card plus a $5 credit that expires in 30 days), SambaNova (20 RPD), Cohere (1K/month), HF (no free credits), GitHub Models (retired), Cloudflare (about 140 calls/day), NVIDIA NIM (40 RPM with no daily cap, but the ToS says prototyping only and no official limits page).

## Switching to the top pick (Groq)

- Base URL: `https://api.groq.com/openai/v1/chat/completions`
- Model id: `openai/gpt-oss-120b`
- Auth: `Authorization: Bearer $GROQ_API_KEY` (key from console.groq.com; free, no card).

`llm.py` hardcodes the URL and the key name, so env vars alone are not enough. Minimal change:

- `harness/cadence/llm.py`: `GOOGLE_URL` -> `LLM_URL = os.environ.get("CADENCE_LLM_URL", "https://api.groq.com/openai/v1/chat/completions")`. Change `load_api_key(name="GEMINI_API_KEY")` to `name="GROQ_API_KEY"` (or take it from a `CADENCE_LLM_KEY_ENV` var). Change the `CADENCE_LLM_MODEL` default to `openai/gpt-oss-120b`. Optionally add `"reasoning_effort": "low"` to the payload. Error strings and the docstring say "google ai studio".
- Other files that name Gemini: `harness/cadence/wiring.py` (`GoogleLLM` import), `harness/tests/test_llm_google.py`, `harness/README.md`, and `CLAUDE.md`.
- Env and secret: put `GROQ_API_KEY=...` in the environment or in `~/.config/cadence/typesafe.env` (never committed). Set `CADENCE_LLM_MODEL=openai/gpt-oss-120b` if the default is not changed.
- Groq returns 400 on `messages[].name`, `logprobs`, `logit_bias`, and `n != 1` (https://console.groq.com/docs/openai). The client sends none of these. `_to_openai` already gives each tool call an `id`, which Groq's tool flow expects.

## Open questions

- Groq's real per-account limits for `llama-3.3-70b-versatile` and `muse-spark-open`: check in the console.
- Mistral free-mode numbers and phone/card requirements: visible only after signup.
- Groq's training policy is not stated on the your-data page. Retention is off by default, which is the practical concern.
