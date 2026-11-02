"""Segmentos de texto transcritos y almacén de los más recientes."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    """Texto dicho entre `start` y `end` (segundos de audio desde el arranque)."""

    start: float
    end: float
    text: str


class Transcript:
    """Guarda los segmentos confirmados de los últimos `max_age_s` segundos."""

    def __init__(self, max_age_s: float = 600) -> None:
        self.max_age_s = max_age_s
        self._segments: deque[Segment] = deque()
        self._lock = threading.Lock()

    def add(self, segments: list[Segment]) -> None:
        with self._lock:
            self._segments.extend(segments)
            if self._segments:
                limit = self._segments[-1].end - self.max_age_s
                while self._segments and self._segments[0].end < limit:
                    self._segments.popleft()

    def since(self, t: float) -> list[Segment]:
        with self._lock:
            return [s for s in self._segments if s.end >= t]
