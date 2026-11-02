"""Comprueba con VODs reales qué entra en el clip de cada ronda (mismo código que en directo, todo en memoria).

    python scripts/clip_vod_check.py "<m3u8>,<apertura en el VOD>,<contraseña>" ["..." ...]

Por cada ronda: baja el audio del VOD alrededor de la apertura, lo mete en el buffer, genera el clip con
`ClipRecorder` (20 s antes → 70 s después, MP3 en memoria), lo decodifica, lo transcribe con Whisper y dice
si la contraseña está dentro del clip. No escribe nada en disco.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

from raffle_listener.audio.buffer import SAMPLE_RATE, AudioRingBuffer  # noqa: E402
from raffle_listener.clips import ClipRecorder  # noqa: E402
from raffle_listener.config import ClipConfig, SttConfig  # noqa: E402
from raffle_listener.extract import normalize  # noqa: E402
from raffle_listener.stt.transcriber import Transcriber  # noqa: E402

LEAD_S = 30  # audio bajado antes de la apertura (más que before_seconds)


def to_seconds(t: str) -> float:
    secs = 0.0
    for part in t.split(":"):
        secs = secs * 60 + float(part)
    return secs


def hms(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02}:{t % 60:02}"


def pcm(cmd: list[str], data: bytes | None = None) -> np.ndarray:
    raw = subprocess.run(cmd, input=data, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("rounds", nargs="+", help="m3u8,apertura(h:mm:ss),contraseña")
    args = ap.parse_args()
    cfg = ClipConfig(stream_delay_seconds=0)  # en el VOD no hay retraso de directo
    stt = Transcriber(SttConfig())
    summary = []
    for spec in args.rounds:
        url, opened, expected = spec.split(",", 2)
        t_open = to_seconds(opened)
        audio = pcm(["ffmpeg", "-loglevel", "error", "-ss", str(t_open - LEAD_S),
                     "-t", str(LEAD_S + cfg.after_seconds + 5), "-i", url, "-vn", "-ac", "1",
                     "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1"])
        buf = AudioRingBuffer(300)
        buf.write(audio)
        mp3, seconds = ClipRecorder(cfg, buf, None).build(at=LEAD_S)
        clip = pcm(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1",
                    "-ar", str(SAMPLE_RATE), "pipe:1"], mp3)
        clip_start = t_open - cfg.before_seconds
        segments = stt.transcribe(clip, clip_start, precise=True)
        key = normalize(expected)
        hits = [s for s in segments if key in normalize(s.text)]
        print(f"\n=== Ronda abierta {opened} · contraseña «{expected}» · clip {hms(clip_start)}–"
              f"{hms(clip_start + seconds)} ({seconds:.0f} s, {len(mp3) / 1024:.0f} KB)")
        for s in segments:
            mark = ">>" if s in hits else "  "
            print(f"{mark} [{hms(s.start)}] {s.text}")
        verdict = f"SÍ, a los {hits[0].start - t_open:+.0f} s de abrir" if hits else "NO está en el clip"
        print(f"→ {verdict}")
        summary.append((opened, expected, verdict))
    print("\nResumen:")
    for opened, expected, verdict in summary:
        print(f"  {opened}  {expected:<24} {verdict}")


if __name__ == "__main__":
    main()
