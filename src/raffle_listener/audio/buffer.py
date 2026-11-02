"""Buffer circular de audio con tiempos en segundos de audio recibido."""

from __future__ import annotations

import threading
import time

import numpy as np

SAMPLE_RATE = 16_000


class AudioRingBuffer:
    """Guarda los últimos `seconds` de audio mono float32 a 16 kHz."""

    def __init__(self, seconds: float, sample_rate: int = SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self.capacity = int(seconds * sample_rate)
        self._buf = np.zeros(self.capacity, dtype=np.float32)
        self._total = 0  # muestras escritas desde el arranque
        self.last_write = 0.0  # time.monotonic() del último audio recibido (0 = nunca)
        self._lock = threading.Lock()

    def silence_seconds(self) -> float:
        """Segundos desde el último audio recibido (infinito si aún no ha llegado nada)."""
        return time.monotonic() - self.last_write if self.last_write else float("inf")

    @property
    def now(self) -> float:
        """Segundos de audio recibidos desde el arranque."""
        return self._total / self.sample_rate

    def write(self, samples: np.ndarray) -> None:
        samples = np.asarray(samples, dtype=np.float32).ravel()
        if len(samples) > self.capacity:
            samples = samples[-self.capacity:]
        with self._lock:
            start = self._total % self.capacity
            first = min(len(samples), self.capacity - start)
            self._buf[start:start + first] = samples[:first]
            self._buf[:len(samples) - first] = samples[first:]
            self._total += len(samples)
        self.last_write = time.monotonic()

    def read(self, start_s: float, end_s: float | None = None) -> tuple[np.ndarray, float]:
        """Devuelve (audio, segundo_real_de_inicio); recorta a lo que aún está guardado."""
        with self._lock:
            oldest = max(0, self._total - self.capacity)
            a = max(oldest, int(start_s * self.sample_rate))
            b = self._total if end_s is None else min(self._total, int(end_s * self.sample_rate))
            if b <= a:
                return np.zeros(0, dtype=np.float32), a / self.sample_rate
            idx = np.arange(a, b) % self.capacity
            return self._buf[idx].copy(), a / self.sample_rate
