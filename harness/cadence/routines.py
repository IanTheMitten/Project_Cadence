import re

from cadence.store import Store


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def match(store: Store, text: str) -> dict | None:
    key = normalize(text)
    for routine in store.list_routines():
        if routine["trigger_type"] != "utterance":
            continue
        if routine["trigger_value"] == key:
            return routine
    return None


def crystallize(store: Store, text: str, steps: list[dict]) -> int:
    key = normalize(text)
    for routine in store.list_routines():
        if routine["trigger_type"] == "utterance" and routine["trigger_value"] == key:
            store.delete_routine(routine["id"])
    return store.save_routine(name=text, trigger_type="utterance", trigger_value=key, steps=steps)


def invalidate(store: Store, text: str) -> int:
    key = normalize(text)
    count = 0
    for routine in store.list_routines():
        if routine["trigger_type"] == "utterance" and routine["trigger_value"] == key:
            store.delete_routine(routine["id"])
            count += 1
    return count
