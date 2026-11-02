"""Reproduce un audio grabado como si fuera el directo, con la app completa (prueba de punta a punta).

    python scripts/replay.py raffle.wav --open-at 180 --close-at 470 --speed 4

`--open-at`/`--close-at` (segundos dentro del archivo) simulan que la web abre/cierra la ronda.
Sin portapapeles ni notificaciones de Windows; los avisos salen por consola.
"""

import argparse
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

import raffle_listener.app as app_module  # noqa: E402
from raffle_listener.audio.buffer import SAMPLE_RATE  # noqa: E402
from raffle_listener.config import Config, load_config  # noqa: E402
from raffle_listener.triggers.site_poller import RaffleEvent  # noqa: E402

CHUNK_S = 0.5


class FileSource:
    def __init__(self, path: str, speed: float) -> None:
        self.path, self.speed = path, speed
        self.done = threading.Event()

    def run(self, on_audio, stop: threading.Event) -> None:
        pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", self.path, "-ac", "1", "-ar", str(SAMPLE_RATE),
                              "-f", "s16le", "pipe:1"], capture_output=True, check=True).stdout
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        step = int(SAMPLE_RATE * CHUNK_S)
        for i in range(0, len(audio), step):
            if stop.is_set():
                break
            on_audio(audio[i:i + step])
            time.sleep(CHUNK_S / self.speed)
        self.done.set()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--open-at", type=float, required=True)
    ap.add_argument("--close-at", type=float)
    ap.add_argument("--speed", type=float, default=4)
    ap.add_argument("--config")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cfg = load_config(args.config) if args.config else Config()
    cfg.trigger.hotkey = cfg.trigger.site_url = ""
    cfg.autojoin.enabled = False
    cfg.output.clipboard = cfg.output.toast = cfg.output.beep = False
    cfg.trigger.listen_after_seconds /= args.speed  # se mide en tiempo real, no en tiempo de audio

    source = FileSource(args.audio, args.speed)
    app_module.make_source = lambda _cfg: source
    app = app_module.App(cfg)
    threading.Thread(target=app.run, daemon=True).start()

    ev = RaffleEvent("replay", "cajas", "no_subs", "open", True)
    opened = closed = False
    while not source.done.wait(0.1):
        if not opened and app.buffer.now >= args.open_at:
            opened = True
            app._on_raffle_open(ev)
        if args.close_at is not None and not closed and app.buffer.now >= args.close_at:
            closed = True
            app._on_raffle_closed()
    time.sleep(cfg.stt.step_seconds + 2)  # dejar que termine la última ventana
    app.stop.set()


if __name__ == "__main__":
    main()
