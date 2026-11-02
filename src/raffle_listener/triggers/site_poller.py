"""Vigila la web de sorteos del canal y avisa cuando se abre uno.

Consulta cada pocos segundos la API JSON de estado público del sitio (`[trigger].site_url`), la misma que usa
su página. El widget de rondas por secciones ("cajas") sale de `cajas.raffle.rounds[]` (una ronda por sección: `no_subs` y `subs`).
Los sorteos genéricos (`raffles.raffles[]`, p. ej. "Raffle 5 × $5" desde el streamdeck) y los Guess
(`guess.guesses[]` / `guess.guess`) usan `status`, `participationOpen` y `passwordRequired` (la web da un Guess
por "abierta" si no está "closed"/"cancelled" y `participationOpen` es verdadero). La API pública NO incluye la
contraseña: solo dice si hay algo abierto y si pide contraseña.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.request
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)

CLOSED_STATUSES = {"drawn", "closed", "cancelled", "finished", "ended"}


@dataclass(frozen=True)
class RaffleEvent:
    id: str
    kind: str              # "cajas", "raffle" o "guess"
    section: str           # "no_subs", "subs" o el título
    status: str
    password_required: bool


def _accepting(r: dict) -> bool:
    """Ronda en la que aún se puede entrar con contraseña (si no pide contraseña, no hay nada que escuchar).

    Los sorteos genéricos siguen en `status: "active"` tras cerrar la participación (`participationOpen: false`).
    """
    return (r.get("status") not in CLOSED_STATUSES and r.get("participationOpen", True) is not False
            and bool(r.get("passwordRequired", True)))


def open_raffles(state: dict) -> list[RaffleEvent]:
    """Extrae las rondas/sorteos abiertos que piden contraseña del JSON de live-state."""
    events: list[RaffleEvent] = []
    cajas = ((state.get("cajas") or {}).get("raffle")) or {}
    for r in cajas.get("rounds") or []:
        if _accepting(r):
            events.append(RaffleEvent(str(r.get("id")), "cajas", str(r.get("section", "")),
                                      str(r.get("status")), True))
    for r in (state.get("raffles") or {}).get("raffles") or []:
        if _accepting(r):
            events.append(RaffleEvent(str(r.get("id")), "raffle", str(r.get("section") or r.get("title") or ""),
                                      str(r.get("status")), True))
    for g in guesses(state):
        if _accepting(g):
            events.append(RaffleEvent(str(g.get("id")), "guess", str(g.get("title") or ""), str(g.get("status")), True))
    return events


def guesses(state: dict) -> list[dict]:
    """Los Guess del estado: la lista `guess.guesses` más el `guess.guess` suelto, sin repetir."""
    section = state.get("guess") or {}
    items = list(section.get("guesses") or [])
    single = section.get("guess")
    if isinstance(single, dict) and all(single.get("id") != g.get("id") for g in items):
        items.append(single)
    return [g for g in items if isinstance(g, dict)]


class SitePoller:
    """Llama a `on_open` por cada ronda nueva y a `on_closed` cuando ya no queda ninguna abierta."""

    def __init__(self, url: str, interval_s: float, on_open: Callable[[RaffleEvent], None],
                 on_closed: Callable[[], None] = lambda: None,
                 on_state: Callable[[dict], None] = lambda _s: None) -> None:
        self.url = url
        self.interval_s = interval_s
        self.on_open = on_open
        self.on_closed = on_closed
        self.on_state = on_state  # recibe el JSON entero en cada consulta (lo usa el aviso de ganadores)

    def fetch(self) -> dict:
        req = urllib.request.Request(self.url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)

    def run(self, stop: threading.Event) -> None:
        seen: set[str] = set()
        was_open = False
        delay = self.interval_s
        log.info("Vigilando sorteos en %s cada %.0f s", self.url, self.interval_s)
        while not stop.is_set():
            try:
                state = self.fetch()
                self.on_state(state)
                events = open_raffles(state)
                for ev in events:
                    if ev.id not in seen:
                        seen.add(ev.id)
                        self.on_open(ev)
                if was_open and not events:
                    self.on_closed()
                was_open = bool(events)
                delay = self.interval_s
            except Exception as exc:
                delay = min(delay * 2, 60)
                log.warning("No se pudo leer el estado de la web (%s); reintento en %.0f s", exc, delay)
            stop.wait(delay)
