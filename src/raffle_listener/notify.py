"""Avisos al usuario: consola, portapapeles, toast de Windows, pitido y Discord. No escribe nada en disco."""

from __future__ import annotations

import json
import logging
import threading
import urllib.request

from .config import OutputConfig
from .extract import Candidate, variants

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, cfg: OutputConfig) -> None:
        self.cfg = cfg

    def info(self, message: str) -> None:
        log.info(message)
        self._toast("Raffle", message)

    def alert(self, candidates: list[Candidate], reason: str, provisional: bool = False) -> None:
        best, others = candidates[0], candidates[1:4]
        lines = [
            "",
            "=" * 60,
            f"  {'POSIBLE CONTRASEÑA' if provisional else 'CONTRASEÑA'}: {best.typed}    (oído: «{best.text}», confianza {best.score:.2f}, {reason})",
            f"  variantes:  {' | '.join(variants(best.text, best.joined))}",
            f"  contexto:   …{best.context}…",
        ]
        lines += [f"  alternativa: {c.text} ({c.score:.2f})" for c in others]
        lines.append("=" * 60)
        print("\n".join(lines), flush=True)

        if self.cfg.clipboard:
            try:
                import pyperclip

                pyperclip.copy(best.typed)
            except Exception as exc:
                log.warning("No se pudo copiar al portapapeles: %s", exc)
        if self.cfg.beep:
            try:
                import winsound

                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                pass
        title = f"¿Contraseña?: {best.typed}" if provisional else f"Contraseña: {best.typed}"
        note = "provisional, se confirma en <30 s" if provisional else "confirmada"
        self._toast(title, f"Copiada al portapapeles · {note} · confianza {best.score:.2f}")
        if self.cfg.discord_webhook and (not provisional or self.cfg.discord_provisional):
            threading.Thread(target=self.send_discord, args=(self.cfg.discord_message + best.typed,),
                             daemon=True).start()

    def send_discord(self, content: str) -> bool:
        """Publica `content` en el canal del webhook. Devuelve si Discord lo aceptó."""
        req = urllib.request.Request(
            self.cfg.discord_webhook,
            data=json.dumps({"content": content}).encode("utf-8"),
            # Discord rechaza el User-Agent por defecto de urllib.
            headers={"Content-Type": "application/json", "User-Agent": "raffle-listener/0.1"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                ok = 200 <= resp.status < 300
        except Exception as exc:
            log.warning("No se pudo enviar a Discord: %s", exc)
            return False
        log.info("Enviado a Discord: %s", content)
        return ok

    def _toast(self, title: str, body: str) -> None:
        if not self.cfg.toast:
            return
        try:
            from win11toast import notify

            notify(title, body)
        except Exception as exc:
            log.debug("Toast no disponible: %s", exc)
