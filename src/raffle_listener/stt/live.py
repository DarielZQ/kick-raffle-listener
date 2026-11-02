"""Transcripción en vivo con ventana deslizante.

Whisper no es streaming: cada `step_seconds` se transcribe el audio desde el último segmento
confirmado hasta ahora, y solo se confirman los segmentos que terminaron hace más de
`holdback_seconds` (los más recientes pueden cambiar cuando llegue más audio).
Mientras `is_active()` sea falso no se transcribe nada (el audio sigue llegando al buffer).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from ..audio.buffer import AudioRingBuffer
from ..config import SttConfig
from ..transcript import Segment, Transcript
from .transcriber import Transcriber

log = logging.getLogger(__name__)

PREROLL_S = 0.15  # margen antes del inicio de un segmento pendiente
SILENCE_S = 1.0   # silencio tras el último segmento para darlo por terminado


class LiveTranscriber:
    def __init__(self, transcriber: Transcriber, buffer: AudioRingBuffer, transcript: Transcript,
                 cfg: SttConfig, on_commit: Callable[[list[Segment]], None],
                 is_active: Callable[[], bool] = lambda: True) -> None:
        self.transcriber = transcriber
        self.is_active = is_active
        self.buffer = buffer
        self.transcript = transcript
        self.cfg = cfg
        self.on_commit = on_commit

    def run(self, stop: threading.Event) -> None:
        committed = 0.0
        last_run = 0.0
        while not stop.is_set():
            now = self.buffer.now
            if not self.is_active():
                committed = last_run = now  # al activarse, empezar desde aquí (lo anterior lo cubre el re-análisis)
                stop.wait(0.5)
                continue
            if now - last_run < self.cfg.step_seconds:
                stop.wait(0.2)
                continue
            last_run = now

            start = committed - PREROLL_S
            if now - start > self.cfg.max_window_seconds:
                log.warning("La transcripción va retrasada; se saltan %.1f s de audio",
                            now - self.cfg.max_window_seconds - start)
                start = now - self.cfg.max_window_seconds
            audio, start = self.buffer.read(start, now)

            t0 = time.perf_counter()
            segments = [s for s in self.transcriber.transcribe(audio, start) if s.end > committed]
            elapsed = time.perf_counter() - t0

            # Un segmento está terminado si Whisper ya empezó otro después, o si tras él hay silencio.
            # El siguiente ciclo empieza justo donde empieza el primer segmento sin terminar: así nunca
            # se corta una palabra por la mitad (con solapamiento salían restos tipo "…seña").
            final_limit = now - self.cfg.holdback_seconds
            done = [s for s in segments[:-1] if s.end <= final_limit]
            if segments and len(done) == len(segments) - 1 and segments[-1].end <= final_limit - SILENCE_S:
                done.append(segments[-1])
            if len(done) < len(segments):
                committed = max(committed, segments[len(done)].start)
            elif done:
                committed = done[-1].end
            else:
                committed = max(committed, final_limit)  # silencio
            if done:
                self.transcript.add(done)
                for s in done:
                    log.debug("[%7.1f] %s", s.start, s.text)
                self.on_commit(done)
            log.debug("ventana %.1f s transcrita en %.2f s", now - start, elapsed)
