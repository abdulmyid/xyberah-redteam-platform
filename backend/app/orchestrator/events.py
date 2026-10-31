"""Live campaign events: written to a JSONL file per campaign and fanned out to
SSE subscribers. Late subscribers get the file replayed first.

Events are published from the campaign's background thread, while SSE subscribers
await on the event loop. asyncio.Queue is not thread-safe and a cross-thread
put_nowait does not wake the awaiting getter, so we deliver via the subscriber's
own loop with call_soon_threadsafe.
"""
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
        # campaign_id -> {queue: event_loop}
        self.subscribers: dict[int, dict[asyncio.Queue, asyncio.AbstractEventLoop]] = defaultdict(dict)

    def publish(self, campaign_id: int, kind: str, **data: Any) -> None:
        event = {"ts": time.time(), "kind": kind, **data}
        with events_file(campaign_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        for q, loop in list(self.subscribers[campaign_id].items()):
            try:
                # Schedule the put on the subscriber's loop so the awaiting getter
                # wakes immediately, regardless of which thread we publish from.
                loop.call_soon_threadsafe(self._deliver, q, event)
            except RuntimeError:
                # loop already closed; drop the dead subscriber
                self.subscribers[campaign_id].pop(q, None)

    @staticmethod
    def _deliver(q: asyncio.Queue, event: dict) -> None:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass  # slow consumer: drop this event rather than block

    def history(self, campaign_id: int, limit: int = 2000) -> list[dict]:
        path = events_file(campaign_id)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        return [json.loads(line) for line in lines if line.strip()]

    def subscribe(self, campaign_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self.subscribers[campaign_id][q] = asyncio.get_running_loop()
        return q

    def unsubscribe(self, campaign_id: int, q: asyncio.Queue) -> None:
        self.subscribers[campaign_id].pop(q, None)


bus = EventBus()
