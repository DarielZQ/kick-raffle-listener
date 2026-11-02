"""Clip de audio de cada ronda → Discord, y se borra a los X minutos. Nunca toca el disco.

Al abrirse una ronda se toma del buffer de memoria el audio de `before_seconds` antes a `after_seconds`
después de la apertura, se comprime a MP3 con ffmpeg (tubería, en memoria) y se sube al webhook. Pasados
`delete_after_minutes` se borra el mensaje (y Discord borra el archivo). Si cierras el bot antes, los clips
pendientes se borran al salir.

La API de la web marca la apertura en tiempo real, pero el audio de Kick llega `stream_delay_seconds` tarde:
el instante de apertura en el audio es `buffer.now + stream_delay_seconds` en el momento del aviso.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
import time
import urllib.request
import uuid

import numpy as np

from .audio.buffer import AudioRingBuffer
from .config import ClipConfig

log = logging.getLogger(__name__)

EXTRA_WAIT_S = 60  # si el audio va lento o se corta, cuánto más esperar antes de enviar lo que haya
USER_AGENT = "raffle-listener/0.1"


def encode_mp3(audio: np.ndarray, sample_rate: int, bitrate: str, speed: float = 1.0) -> bytes:
    """PCM float32 mono → MP3 en memoria (ffmpeg por tuberías, sin archivos).

    `speed` ≠ 1 acelera sin cambiar el tono de la voz (filtro `atempo`): x2 dura la mitad y pesa la mitad.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("No se encontró ffmpeg en el PATH")
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()
    tempo = ["-af", f"atempo={speed:g}"] if speed != 1 else []
    cmd = [ffmpeg, "-loglevel", "error", "-f", "s16le", "-ar", str(sample_rate), "-ac", "1", "-i", "pipe:0",
           *tempo, "-c:a", "libmp3lame", "-b:a", bitrate, "-f", "mp3", "pipe:1"]
    return subprocess.run(cmd, input=pcm, capture_output=True, check=True).stdout


def _multipart(fields: dict[str, tuple[str | None, str, bytes]]) -> tuple[bytes, str]:
    """Cuerpo multipart/form-data: {nombre: (archivo|None, content-type, datos)}."""
    boundary = uuid.uuid4().hex
    parts = []
    for name, (filename, ctype, data) in fields.items():
        disp = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
        parts.append(f"--{boundary}\r\nContent-Disposition: {disp}\r\nContent-Type: {ctype}\r\n\r\n".encode() + data + b"\r\n")
    return b"".join(parts) + f"--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


class DiscordClips:
    """Sube clips a un webhook y los borra pasado un tiempo."""

    def __init__(self, webhook: str) -> None:
        self.base = webhook.split("?")[0].rstrip("/")
        self._pending: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def upload(self, files: list[tuple[str, bytes]], content: str) -> str:
        """Un mensaje con uno o varios MP3 adjuntos [(nombre, datos)]; devuelve el id del mensaje."""
        attachments = [{"id": i, "filename": name} for i, (name, _) in enumerate(files)]
        payload = json.dumps({"content": content, "attachments": attachments}).encode()
        fields = {"payload_json": (None, "application/json", payload)}
        for i, (name, data) in enumerate(files):
            fields[f"files[{i}]"] = (name, "audio/mpeg", data)
        body, ctype = _multipart(fields)
        req = urllib.request.Request(f"{self.base}?wait=true", data=body, method="POST",
                                     headers={"Content-Type": ctype, "User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return str(json.load(resp)["id"])

    def delete(self, message_id: str) -> None:
        req = urllib.request.Request(f"{self.base}/messages/{message_id}", method="DELETE",
                                     headers={"User-Agent": USER_AGENT})
        try:
            urllib.request.urlopen(req, timeout=15).close()
            log.info("Clip borrado de Discord (mensaje %s)", message_id)
        except Exception as exc:
            log.warning("No se pudo borrar el clip %s de Discord: %s", message_id, exc)
        with self._lock:
            self._pending.pop(message_id, None)

    def schedule_delete(self, message_id: str, after_s: float) -> None:
        timer = threading.Timer(after_s, self.delete, args=(message_id,))
        timer.daemon = True
        with self._lock:
            self._pending[message_id] = timer
        timer.start()

    def flush(self) -> None:
        """Al cerrar el bot: borra ya los clips que aún esperaban su hora."""
        with self._lock:
            pending = list(self._pending.items())
        for message_id, timer in pending:
            timer.cancel()
            self.delete(message_id)


class ClipRecorder:
    """Graba el clip de una ronda desde el buffer y lo manda a Discord."""

    def __init__(self, cfg: ClipConfig, buffer: AudioRingBuffer, discord: DiscordClips | None) -> None:
        self.cfg = cfg
        self.buffer = buffer
        self.discord = discord

    def capture(self, reason: str, at: float | None = None, message: str | None = None) -> threading.Thread:
        """Arranca en segundo plano el clip de una apertura. `at` = instante de apertura en tiempo de audio."""
        if at is None:
            at = self.buffer.now + self.cfg.stream_delay_seconds
        t = threading.Thread(target=self._run, args=(reason, at, message or self.cfg.message), name="clip",
                             daemon=True)
        t.start()
        return t

    def build(self, at: float) -> tuple[bytes, float]:
        """Espera a tener el audio hasta `at + after` y devuelve (mp3, segundos de audio)."""
        audio = self.collect(at)
        if len(audio) == 0:
            return b"", 0.0
        return encode_mp3(audio, self.buffer.sample_rate, self.cfg.bitrate), len(audio) / self.buffer.sample_rate

    def collect(self, at: float) -> np.ndarray:
        """Audio de `at - before` a `at + after`, esperando a que llegue (o hasta un límite)."""
        end = at + self.cfg.after_seconds
        deadline = time.monotonic() + self.cfg.after_seconds + self.cfg.stream_delay_seconds + EXTRA_WAIT_S
        while self.buffer.now < end and time.monotonic() < deadline:
            time.sleep(0.5)
        if self.buffer.now < end:
            log.warning("El audio no llegó entero a tiempo: el clip saldrá más corto")
        audio, _ = self.buffer.read(at - self.cfg.before_seconds, end)
        return audio

    def files(self, audio: np.ndarray) -> list[tuple[str, bytes]]:
        """El clip normal y sus copias aceleradas (`speed_copies`), todo en memoria."""
        stem = time.strftime("raffle-%H%M%S")
        sr, br = self.buffer.sample_rate, self.cfg.bitrate
        out = [(f"{stem}.mp3", encode_mp3(audio, sr, br))]
        out += [(f"{stem}-x{s:g}.mp3", encode_mp3(audio, sr, br, speed=s)) for s in self.cfg.speed_copies]
        return out

    def _run(self, reason: str, at: float, message: str) -> None:
        try:
            audio = self.collect(at)
            seconds = len(audio) / self.buffer.sample_rate
            if len(audio) == 0:
                log.warning("Sin audio para el clip (%s)", reason)
                return
            if self.discord is None:
                log.info("Clip de %.0f s listo (%s), pero no hay webhook de Discord configurado", seconds, reason)
                return
            files = self.files(audio)
            message_id = self.discord.upload(files, message)
            sizes = " + ".join(f"{name} {len(data) / 1024:.0f} KB" for name, data in files)
            log.info("Clip de %.0f s enviado a Discord (%s); se borra en %.0f min",
                     seconds, sizes, self.cfg.delete_after_minutes)
            self.discord.schedule_delete(message_id, self.cfg.delete_after_minutes * 60)
        except Exception:
            log.exception("No se pudo enviar el clip (%s)", reason)
