"""SSE event bus: a publish from a background thread must wake a subscriber awaiting
on the event loop (the live-log 'freeze' regression)."""
import asyncio
import threading

from app.orchestrator.events import bus


def test_cross_thread_publish_wakes_subscriber():
    async def run():
        q = bus.subscribe(987654)
        # Publish from a different thread, like the campaign runner does.
        threading.Thread(target=lambda: bus.publish(987654, "log", line="hi"), daemon=True).start()
        try:
            ev = await asyncio.wait_for(q.get(), timeout=3)
        finally:
            bus.unsubscribe(987654, q)
        return ev

    ev = asyncio.run(run())
    assert ev["kind"] == "log" and ev["line"] == "hi"
