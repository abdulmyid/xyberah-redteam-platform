"""Live campaign events: written to a JSONL file per campaign and fanned out to
SSE subscribers. Late subscribers get the file replayed first."""
import asyncio
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..config import get_settings


def events_file(campaign_id: int) -> Path:
    d = get_settings().campaigns_dir / str(campaign_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / "events.jsonl"


class EventBus:
    def __init__(self) -> None:
        self.subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)

    def publish(self, campaign_id: int, kind: str, **data: Any) -> None:
        event = {"ts": time.time(), "kind": kind, **data}
        with events_file(campaign_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        for q in list(self.subscribers[campaign_id]):
            q.put_nowait(event)

    def history(self, campaign_id: int, limit: int = 2000) -> list[dict]:
        path = events_file(campaign_id)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        return [json.loads(line) for line in lines if line.strip()]

    def subscribe(self, campaign_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self.subscribers[campaign_id].add(q)
        return q

    def unsubscribe(self, campaign_id: int, q: asyncio.Queue) -> None:
        self.subscribers[campaign_id].discard(q)


bus = EventBus()
