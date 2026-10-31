"""Public red-team dataset packs, fetched on demand from their canonical sources and
imported (read-only) into a prompt set. Nothing is bundled/redistributed — the data is
pulled from the official repo at import time, with source attribution preserved."""
import csv
import io
from functools import lru_cache

import httpx

PACKS = {
    "harmbench": {
        "name": "HarmBench (text behaviors, all)",
        "source": "https://github.com/centerforaisafety/HarmBench",
        "url": "https://raw.githubusercontent.com/centerforaisafety/HarmBench/main/data/behavior_datasets/harmbench_behaviors_text_all.csv",
        "column": "Behavior", "count": 400,
        "desc": "Standardized harmful-behavior red-teaming benchmark (CAIS).",
    },
    "do-not-answer": {
        "name": "Do-Not-Answer",
        "source": "https://huggingface.co/datasets/LibrAI/do-not-answer",
        "url": "https://huggingface.co/datasets/LibrAI/do-not-answer/resolve/main/data_en.csv",
        "column": "question", "count": 939,
        "desc": "Questions a responsible model should refuse — great for refusal testing (LibrAI).",
    },
    "jailbreakbench": {
        "name": "JailbreakBench (harmful behaviors)",
        "source": "https://huggingface.co/datasets/JailbreakBench/JBB-Behaviors",
        "url": "https://huggingface.co/datasets/JailbreakBench/JBB-Behaviors/resolve/main/data/harmful-behaviors.csv",
        "column": "Goal", "count": 100,
        "desc": "Curated jailbreak behaviors benchmark (JailbreakBench).",
    },
}


def sources() -> list[dict]:
    return [{"id": "dataset::" + k, "provider": "dataset", "name": p["name"],
             "count": p["count"], "source": p["source"], "desc": p["desc"]}
            for k, p in PACKS.items()]


@lru_cache(maxsize=16)
def fetch(pack_id: str) -> tuple[str, ...]:
    """Fetch and parse a pack's prompt column. Cached. Raises on network/parse error."""
    p = PACKS[pack_id]
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        r = c.get(p["url"])
        r.raise_for_status()
        text = r.text
    col = p["column"]
    out, seen = [], set()
    for row in csv.DictReader(io.StringIO(text)):
        v = (row.get(col) or "").strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return tuple(out)
