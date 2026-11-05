"""Off-loop execution of CPU-bound detection.

Large inputs go to a ``ProcessPoolExecutor`` (true parallelism, no GIL contention
with the event loop); small inputs go to ``asyncio.to_thread``, where the process
round-trip would cost more than the scan. If the pool breaks (e.g. a worker is
OOM-killed) it is rebuilt and the call falls back to a thread.
"""
from __future__ import annotations

import asyncio
import logging
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any, Optional

from .engine import detect_many

log = logging.getLogger("xyberah.gateway.executor")

PROCESS_THRESHOLD_CHARS = int(os.getenv("XYBERAH_GATEWAY_PROCESS_THRESHOLD", "4096"))


class DetectionExecutor:
    """Runs :func:`engine.detect_many` without blocking the event loop."""

    def __init__(self, workers: Optional[int] = None) -> None:
        """``workers=None`` sizes the pool to min(4, CPUs); ``0`` uses threads only."""
        self._workers = max(1, min(4, os.cpu_count() or 1)) if workers is None else max(0, workers)
        self._pool: Optional[ProcessPoolExecutor] = None

    @property
    def workers(self) -> int:
        """Configured process-pool size."""
        return self._workers

    def start(self) -> None:
        """Create the process pool and warm workers (compiles regexes once per worker)."""
        if self._workers <= 0:
            return
        ctx = multiprocessing.get_context("forkserver" if os.name != "nt" else "spawn")
        self._pool = ProcessPoolExecutor(max_workers=self._workers, mp_context=ctx)
        warm_rules: list[dict[str, Any]] = [{"id": 0, "name": "warm", "kind": "injection", "direction": "both",
                                              "action": "log", "config": {}}]
        for _ in range(self._workers):
            self._pool.submit(detect_many, [("user", "warm up")], warm_rules, "inbound")

    def shutdown(self) -> None:
        """Stop worker processes."""
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None

    async def detect(self, items: list[tuple[str, str]], rules: list[dict[str, Any]], direction: str,
                     classifiers: bool = True) -> list[list[dict[str, Any]]]:
        """Detect over ``items`` off the event loop."""
        if not rules or not items:
            return [[] for _ in items]
        size = sum(len(t) for _, t in items)
        if self._pool is not None and size >= PROCESS_THRESHOLD_CHARS:
            loop = asyncio.get_running_loop()
            try:
                return await loop.run_in_executor(self._pool, detect_many, items, rules, direction, classifiers)
            except BrokenProcessPool:
                log.error("detection process pool broke; rebuilding")
                self.shutdown()
                self.start()
        return await asyncio.to_thread(detect_many, items, rules, direction, classifiers)
