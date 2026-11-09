"""Pre-render acknowledgement clips per category into <out>/<category>/NN.pcm."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cadence_speaker.acks import ACK_CATEGORIES
from cadence_speaker.audio.tts import Tts
from ollama_llm import OllamaLLM

SITUATIONS = {
    "action": "right after being asked to do something like play music or pause",
    "chat": "right before answering a question or chatting",
    "correction": "right after the user says it got something wrong",
}


def parse_phrases(text: str, n: int) -> list[str]:
    start, end = text.find("["), text.rfind("]")
    items = json.loads(text[start : end + 1])
    seen: set[str] = set()
    phrases: list[str] = []
    for item in items:
        phrase = str(item).strip()
        key = phrase.lower()
        if not phrase or key in seen:
            continue
        seen.add(key)
        phrases.append(phrase)
    return phrases[:n]


async def generate(llm: OllamaLLM, category: str, n: int) -> list[str]:
    prompt = (
        f"Write {n} different short spoken acknowledgements a home speaker says "
        f"{SITUATIONS[category]}. 1 to 4 words each, casual, no emojis. "
        "Answer with a JSON array of strings only."
    )
    reply = await llm.chat([{"role": "user", "content": prompt}], tools=[], think=True)
    return parse_phrases(reply["message"]["content"], n)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="acks")
    ap.add_argument("--per-category", type=int, default=20)
    args = ap.parse_args()

    out = Path(args.out)
    llm = OllamaLLM()
    tts = Tts()
    result: dict[str, list[str]] = {}
    for category in ACK_CATEGORIES:
        phrases = await generate(llm, category, args.per_category)
        d = out / category
        d.mkdir(parents=True, exist_ok=True)
        for i, phrase in enumerate(phrases):
            (d / f"{i:02d}.pcm").write_bytes(tts.speak(phrase))
        result[category] = phrases
        print(f"{category}: {len(phrases)} clips")
    (out / "phrases.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
