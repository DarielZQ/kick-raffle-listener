"""Envoltorio de faster-whisper: carga en GPU (con fallback a CPU) y transcribe con lock."""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

import numpy as np

from ..config import SttConfig
from ..transcript import Segment

log = logging.getLogger(__name__)

# Sesga el vocabulario hacia lo que nos interesa en el re-análisis.
# "la pass es" para que no lo transcriba como "la paz es".
RAFFLE_PROMPT = "Directo de Kick. Sorteo, raffle, cajas. La contraseña es, la pass es, la clave es, la palabra es."


def _add_nvidia_dll_dirs() -> None:
    """En Windows, CTranslate2 necesita las DLL de cuBLAS/cuDNN instaladas con pip (extra `cuda`)."""
    if sys.platform != "win32":
        return
    for site in map(Path, sys.path):
        nvidia = site / "nvidia"
        if not nvidia.is_dir():
            continue
        for bin_dir in nvidia.glob("*/bin"):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"


class Transcriber:
    def __init__(self, cfg: SttConfig) -> None:
        from faster_whisper import WhisperModel

        self.language = cfg.language
        self._lock = threading.Lock()
        _add_nvidia_dll_dirs()
        try:
            self.model = WhisperModel(cfg.model, device=cfg.device, compute_type=cfg.compute_type)
            # Forzar una inferencia para que falle aquí (y no más tarde) si faltan DLL de CUDA.
            list(self.model.transcribe(np.zeros(16_000, dtype=np.float32), language=self.language)[0])
            log.info("Whisper '%s' cargado en %s (%s)", cfg.model, cfg.device, cfg.compute_type)
        except Exception as exc:
            if cfg.device == "cpu":
                raise
            log.warning("No se pudo usar %s (%s). Usando CPU con 'small'.", cfg.device, exc)
            self.model = WhisperModel("small", device="cpu", compute_type="int8")

    def transcribe(self, audio: np.ndarray, offset_s: float, *, precise: bool = False) -> list[Segment]:
        """Transcribe `audio`; los tiempos devueltos se desplazan `offset_s` segundos."""
        if len(audio) == 0:
            return []
        with self._lock:
            segments, _ = self.model.transcribe(
                audio,
                language=self.language,
                beam_size=5 if precise else 1,
                vad_filter=True,
                condition_on_previous_text=False,
                initial_prompt=RAFFLE_PROMPT if precise else None,
            )
            return [Segment(offset_s + s.start, offset_s + s.end, s.text.strip())
                    for s in segments if s.text.strip()]
