"""Fuentes de audio: stream de Kick (streamlink + ffmpeg) o loopback de Windows."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
import time
from typing import Callable

import numpy as np

from ..config import StreamConfig
from .buffer import SAMPLE_RATE

log = logging.getLogger(__name__)

OnAudio = Callable[[np.ndarray], None]
CHUNK_SECONDS = 0.5
STALL_SECONDS = 20       # sin audio durante este tiempo → se reinicia la conexión
RECONNECT_SECONDS = 30   # con el directo apagado, cada cuánto se vuelve a comprobar


class KickSource:
    """`streamlink --stdout https://kick.com/<canal> | ffmpeg → PCM 16 kHz mono`.

    Reconecta si el stream se corta **y también si se queda colgado sin cerrarse**: streamlink puede dejar
    de recibir datos con las conexiones abiertas, y entonces la lectura se queda bloqueada para siempre y las
    rondas pasan sin audio. Un hilo vigilante mata los procesos si no llega audio en `stall_s` segundos.

    Se puede arrancar horas antes del directo: mientras esté apagado lo avisa una vez y lo comprueba cada
    `reconnect_s` en silencio; cuando empieza, se conecta solo.
    """

    def __init__(self, channel: str, quality: str = "worst", stall_s: float = STALL_SECONDS,
                 reconnect_s: float = RECONNECT_SECONDS) -> None:
        if not channel:
            raise ValueError("Falta [stream].channel en config.toml")
        self.url = f"https://kick.com/{channel}"
        self.quality = quality
        self.stall_s = stall_s
        self.reconnect_s = reconnect_s
        self._procs: list[subprocess.Popen] = []
        self._lock = threading.Lock()

    def commands(self) -> tuple[list[str], list[str]]:
        streamlink = shutil.which("streamlink")
        sl_base = [streamlink] if streamlink else [sys.executable, "-m", "streamlink"]
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("No se encontró ffmpeg en el PATH")
        sl_cmd = sl_base + ["--stdout", "--loglevel", "warning", "--stream-timeout", str(int(self.stall_s)),
                            self.url, self.quality]
        ff_cmd = [ffmpeg, "-loglevel", "error", "-i", "pipe:0", "-vn", "-ac", "1",
                  "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1"]
        return sl_cmd, ff_cmd

    def restart(self, reason: str) -> None:
        """Corta la conexión actual; el bucle de `run` vuelve a conectar enseguida."""
        with self._lock:
            procs = list(self._procs)
        if procs:
            log.warning("Reiniciando la conexión con Kick: %s", reason)
        for p in procs:
            p.kill()

    def run(self, on_audio: OnAudio, stop: threading.Event) -> None:
        sl_cmd, ff_cmd = self.commands()
        chunk_bytes = int(SAMPLE_RATE * CHUNK_SECONDS) * 2
        waiting = False  # ya se avisó de que el directo está apagado

        while not stop.is_set():
            (log.debug if waiting else log.info)("Conectando a %s", self.url)
            sl = subprocess.Popen(sl_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # Sus mensajes ("No playable streams found…" cada 30 s mientras está apagado) van al log de depuración;
            # hay que leerlos siempre o, en horas de directo, la tubería se llenaría y streamlink se bloquearía.
            threading.Thread(target=_drain, args=(sl.stderr, "streamlink"), name="streamlink-log", daemon=True).start()
            ff = subprocess.Popen(ff_cmd, stdin=sl.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # Igual con ffmpeg: con el directo apagado recibe una entrada vacía y se queja ("Invalid data found…")
            # en cada comprobación; eso no es un error del bot.
            threading.Thread(target=_drain, args=(ff.stderr, "ffmpeg"), name="ffmpeg-log", daemon=True).start()
            sl.stdout.close()  # ffmpeg es el único lector
            with self._lock:
                self._procs = [ff, sl]
            last_data = time.monotonic()
            stalled = threading.Event()
            done = threading.Event()

            def watchdog() -> None:
                while not done.wait(1):
                    silent = time.monotonic() - last_data
                    if silent > self.stall_s:
                        stalled.set()
                        self.restart(f"no llega audio desde hace {silent:.0f} s")
                        return

            threading.Thread(target=watchdog, name="audio-watchdog", daemon=True).start()
            got_audio = False
            try:
                while not stop.is_set():
                    data = ff.stdout.read(chunk_bytes)
                    if not data:
                        break
                    last_data = time.monotonic()
                    if not got_audio:
                        got_audio = True
                        log.info("¡Ha empezado el directo! Audio recibiéndose" if waiting
                                 else "Audio del directo recibiéndose")
                        waiting = False
                    pcm = np.frombuffer(data[: len(data) // 2 * 2], dtype=np.int16)
                    on_audio(pcm.astype(np.float32) / 32768.0)
            finally:
                done.set()
                with self._lock:
                    self._procs = []
                for p in (ff, sl):
                    p.kill()
                    p.wait()
            if stop.is_set():
                break
            if stalled.is_set() or got_audio:
                stop.wait(1)  # estaba funcionando: reconectar ya
                continue
            if not waiting:
                waiting = True
                log.info("El directo de %s no está en marcha. Espero y me conecto solo cuando empiece "
                         "(compruebo cada %.0f s).", self.url, self.reconnect_s)
            stop.wait(self.reconnect_s)


def _drain(stream, name: str) -> None:
    for line in iter(stream.readline, b""):
        log.debug("%s: %s", name, line.decode("utf-8", "replace").rstrip())
    stream.close()


class LoopbackSource:
    """Captura lo que suena por los altavoces (WASAPI loopback)."""

    def restart(self, reason: str) -> None:
        log.warning("Audio parado (%s); con loopback revisa que el directo esté sonando en el PC", reason)

    def run(self, on_audio: OnAudio, stop: threading.Event) -> None:
        import soundcard as sc

        speaker = sc.default_speaker()
        mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
        log.info("Capturando audio de: %s", speaker.name)
        frames = int(SAMPLE_RATE * CHUNK_SECONDS)
        with mic.recorder(samplerate=SAMPLE_RATE, channels=1) as rec:
            while not stop.is_set():
                on_audio(rec.record(numframes=frames)[:, 0])


def make_source(cfg: StreamConfig) -> KickSource | LoopbackSource:
    if cfg.source == "kick":
        return KickSource(cfg.channel, cfg.quality)
    if cfg.source == "loopback":
        return LoopbackSource()
    raise ValueError(f"[stream].source desconocido: {cfg.source!r} (usa 'kick' o 'loopback')")
