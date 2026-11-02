"""Punto de entrada: `python -m raffle_listener --config config.toml`."""

from __future__ import annotations

import argparse
import logging

from .app import App
from .notify import Notifier
from .config import load_config, require_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Detecta la contraseña de los raffles escuchando el stream.")
    parser.add_argument("--config", default="config.toml", help="ruta a config.toml")
    parser.add_argument("-v", "--verbose", action="store_true", help="muestra la transcripción en vivo")
    parser.add_argument("--test-discord", action="store_true", help="envía un mensaje de prueba al webhook y sale")
    parser.add_argument("--login", action="store_true", help="abre el Chrome del bot para iniciar sesión en la web")
    parser.add_argument("--test-clip", action="store_true",
                        help="manda a Discord un clip de prueba de 5 s (un pitido, con su copia x2) y lo borra al minuto")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    if args.verbose:  # solo nuestro código en DEBUG; las librerías (httpx, huggingface…) siguen en INFO
        logging.getLogger("raffle_listener").setLevel(logging.DEBUG)
    for noisy in ("faster_whisper", "urllib3", "httpx", "httpx2", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    cfg = load_config(args.config)
    if args.test_discord:
        if not cfg.output.discord_webhook:
            raise SystemExit("No hay [output].discord_webhook en config.toml")
        # Mismo texto que un aviso real (incluida la mención de un rol, si la lleva).
        ok = Notifier(cfg.output).send_discord(f"{cfg.output.discord_message}prueba")
        raise SystemExit(0 if ok else 1)
    if args.test_clip:
        _test_clip(cfg)
        return
    if args.login:
        from .autojoin import AutoJoiner

        require_settings(cfg, login=True)
        AutoJoiner(cfg.autojoin, cfg.autojoin.page_url, lambda _r: None).login()
        return
    require_settings(cfg)
    App(cfg).run()


def _test_clip(cfg) -> None:
    import time

    import numpy as np

    from .clips import DiscordClips, encode_mp3

    if not cfg.output.discord_webhook:
        raise SystemExit("No hay [output].discord_webhook en config.toml")
    sr = 16_000
    t = np.arange(sr * 5) / sr
    beep = (0.2 * np.sin(2 * np.pi * 440 * t) * (t % 1 < 0.5)).astype(np.float32)  # pitido a pulsos de 1 s
    files = [("prueba.mp3", encode_mp3(beep, sr, cfg.clip.bitrate))]
    files += [(f"prueba-x{s:g}.mp3", encode_mp3(beep, sr, cfg.clip.bitrate, speed=s)) for s in cfg.clip.speed_copies]
    discord = DiscordClips(cfg.output.discord_webhook)
    message_id = discord.upload(files, f"PRUEBA (normal y x2; se borra en 1 min) · {cfg.clip.message}")
    print("Clip de prueba enviado a Discord; se borra en 60 s…", flush=True)
    time.sleep(60)
    discord.delete(message_id)
    print("Borrado.", flush=True)


if __name__ == "__main__":
    main()
