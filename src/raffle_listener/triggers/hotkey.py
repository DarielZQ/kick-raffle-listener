"""Tecla rápida global para forzar un re-análisis (por si la web no avisa)."""

from __future__ import annotations

import logging
import threading
from typing import Callable

log = logging.getLogger(__name__)


class Hotkey:
    def __init__(self, combo: str, on_press: Callable[[], None]) -> None:
        self.combo = combo
        self.on_press = on_press

    def run(self, stop: threading.Event) -> None:
        from pynput import keyboard

        with keyboard.GlobalHotKeys({self.combo: self.on_press}) as listener:
            log.info("Tecla rápida: %s", self.combo)
            stop.wait()
            listener.stop()
