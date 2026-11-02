"""Transcribe un audio/vídeo (o un tramo) y busca contraseñas. Sirve para afinar con VODs pasados.

    python scripts/transcribe_file.py grabacion.mp4 --start 45:00 --duration 300
    python scripts/transcribe_file.py "https://kick.com/<canal>/videos/<id>" --start 1:11:30 --duration 240

Acepta cualquier cosa que lea ffmpeg; si es una URL de Kick, se resuelve con streamlink.
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

from raffle_listener.config import SttConfig  # noqa: E402
from raffle_listener.extract import extract, variants  # noqa: E402
from raffle_listener.stt.transcriber import Transcriber  # noqa: E402


def to_seconds(t: str) -> float:
    secs = 0.0
    for part in t.split(":"):
        secs = secs * 60 + float(part)
    return secs


def resolve(src: str) -> str:
    if src.startswith("http") and "kick.com" in src:
        return subprocess.check_output([sys.executable, "-m", "streamlink", "--stream-url", src, "worst"],
                                       text=True).strip()
    return src


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--start", default="0", help="inicio (s, mm:ss o hh:mm:ss)")
    ap.add_argument("--duration", type=float, default=300, help="segundos a transcribir")
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--precise", action="store_true", help="beam 5 + prompt de sorteo (como el re-análisis)")
    ap.add_argument("--label-start", help="hora del VOD a la que corresponde el inicio (si el archivo ya es un recorte)")
    args = ap.parse_args()

    start = to_seconds(args.start)
    cmd = ["ffmpeg", "-loglevel", "error", "-ss", str(start), "-t", str(args.duration), "-i", resolve(args.source),
           "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"]
    pcm = subprocess.run(cmd, capture_output=True, check=True).stdout
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    print(f"Audio: {len(audio) / 16000:.0f} s")

    stt = Transcriber(SttConfig(model=args.model, device=args.device))
    label = to_seconds(args.label_start) if args.label_start else start
    segments = stt.transcribe(audio, label, precise=args.precise)
    for s in segments:
        m, sec = divmod(int(s.start), 60)
        h, m = divmod(m, 60)
        print(f"[{h}:{m:02}:{sec:02}] {s.text}")

    print("\nCandidatas:")
    for c in extract(segments) or []:
        print(f"  {c.score:.2f}  {c.text!r}  [{c.pattern}, x{c.mentions}]  {' | '.join(variants(c.text))}")


if __name__ == "__main__":
    main()
