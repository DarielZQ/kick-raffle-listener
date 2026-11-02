"""Aviso a Discord cuando gana alguien de tu lista de @ de Discord.

Los ganadores salen en el mismo JSON público que ya consulta el bot (`[trigger].site_url`):
- sorteos genéricos: `raffles.raffles[].confirmedWinners` / `potentialWinners`
- Guess: `guess.guesses[].potentialWinners` (la web los cuenta con `status` "pending" o "confirmed")
- cajas: `cajas.raffle.rounds[].winners` y `cajas.raffle.winnerEntries`
Cada ganador trae `discordId` (único), `discordUsername` (el @ único) y `discordGlobalName`/`displayName`
(el nombre personalizado, que puede repetirse o cambiar: no se usa para comparar). Solo se avisa de ganadores
**confirmados**, porque un ganador generado puede volver a sortearse.

Para que a la persona le llegue la notificación, el mensaje la menciona por su ID (`<@id>`): un "@nombre" en
texto no avisa a nadie. Al arrancar, los ganadores que ya estaban en la web se dan por vistos (no se repiten).
"""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator

from .config import WinnersConfig
from .triggers.site_poller import guesses

log = logging.getLogger(__name__)

USER_AGENT = "raffle-listener/0.1"
CONFIRMED = {"confirmed", "paid", "selected", "pending_selection", "paying", "won"}


@dataclass(frozen=True)
class Win:
    key: str          # tipo:sorteo:discordId → para no avisar dos veces
    kind: str         # "raffle", "guess", "cajas"
    title: str
    discord_id: str
    username: str     # @ de Discord en minúsculas ("" si la web no lo da)
    display: str
    prize_usd: float | None
    when: str | None  # ISO (confirmedAt o similar)


def _clean(name: str | None) -> str:
    return (name or "").strip().lstrip("@").lower()


def _confirmed(w: dict) -> bool:
    status = w.get("status")
    return status is None or status in CONFIRMED


def _win(kind: str, parent: str, title: str, w: dict) -> Win | None:
    discord_id = str(w.get("discordId") or "")
    if not discord_id or not _confirmed(w):
        return None
    prize = w.get("prizeUsd")
    return Win(f"{kind}:{parent}:{discord_id}", kind, title, discord_id, _clean(w.get("discordUsername")),
               str(w.get("discordGlobalName") or w.get("displayName") or w.get("discordUsername") or ""),
               float(prize) if isinstance(prize, (int, float)) else None,
               w.get("confirmedAt") or w.get("paidAt") or w.get("selectedAt") or w.get("createdAt"))


def winners_in(state: dict, rounds_title: str = "Cajas ({section})") -> Iterator[Win]:
    for r in (state.get("raffles") or {}).get("raffles") or []:
        title = str(r.get("title") or "Sorteo")
        lists = r.get("confirmedWinners") or r.get("potentialWinners") or []
        for w in lists:
            if (win := _win("raffle", str(r.get("id")), title, w)) is not None:
                yield win
    for g in guesses(state):
        for w in g.get("confirmedWinners") or g.get("potentialWinners") or g.get("winners") or []:
            if (win := _win("guess", str(g.get("id")), f"Guess: {g.get('title') or ''}".strip(), w)) is not None:
                yield win
    cajas = ((state.get("cajas") or {}).get("raffle")) or {}
    for rd in cajas.get("rounds") or []:
        section = {"no_subs": "No Subs", "subs": "Subs"}.get(rd.get("section"), rd.get("section") or "")
        for w in rd.get("winners") or []:
            if isinstance(w, dict) and (win := _win("cajas", str(rd.get("id")), rounds_title.format(section=section), w)):
                yield win
    for w in cajas.get("winnerEntries") or []:
        section = {"no_subs": "No Subs", "subs": "Subs"}.get(w.get("section"), w.get("section") or "")
        if (win := _win("cajas", str(w.get("roundId")), rounds_title.format(section=section), w)) is not None:
            yield win


def known_usernames(state: dict) -> dict[str, str]:
    """discordId → @ a partir de cualquier objeto del estado que traiga ambos (las cajas no siempre traen el @)."""
    found: dict[str, str] = {}

    def walk(o) -> None:
        if isinstance(o, dict):
            if o.get("discordId") and o.get("discordUsername"):
                found[str(o["discordId"])] = _clean(o["discordUsername"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(state)
    return found


class WinnerWatcher:
    def __init__(self, cfg: WinnersConfig, webhook: str) -> None:
        self.cfg = cfg
        self.webhook = webhook.split("?")[0].rstrip("/") if webhook else ""
        # Se aceptan @ (con o sin "@") o directamente IDs numéricos de Discord.
        self.watch_names = {_clean(u) for u in cfg.usernames if not str(u).strip().isdigit()}
        self.watch_ids = {str(u).strip() for u in cfg.usernames if str(u).strip().isdigit()}
        self.id_to_name: dict[str, str] = {}
        self.seen: set[str] = set()
        self.primed = False

    def on_state(self, state: dict) -> None:
        if not self.cfg.enabled:
            return
        self.id_to_name.update(known_usernames(state))
        wins = list(winners_in(state, self.cfg.rounds_title))
        if not self.primed:  # lo que ya estaba al arrancar no se anuncia
            self.seen.update(w.key for w in wins)
            self.primed = True
            return
        new = [w for w in wins if w.key not in self.seen]
        by_title: dict[str, list[Win]] = {}
        for w in new:
            self.seen.add(w.key)
            by_title.setdefault(w.title, []).append(w)
            name = w.username or self.id_to_name.get(w.discord_id, "")
            if w.discord_id in self.watch_ids or (name and name in self.watch_names):
                self.announce(w, name)
        for title, ws in by_title.items():  # diagnóstico sin nombres: ¿trae la web el @ de Discord?
            with_at = sum(bool(w.username or self.id_to_name.get(w.discord_id)) for w in ws)
            log.info("Ganadores nuevos en %s: %d (con @ de Discord: %d)", title, len(ws), with_at)

    def message(self, w: Win, name: str) -> str:
        when = _local(w.when)
        prize = f" · Premio: {w.prize_usd:g} $" if w.prize_usd else ""
        return self.cfg.message.format(mention=f"<@{w.discord_id}>", username=name or w.display,
                                       sorteo=w.title, premio=prize, fecha=when.strftime("%d/%m/%Y"),
                                       hora=when.strftime("%H:%M"))

    def announce(self, w: Win, name: str) -> None:
        content = self.message(w, name)
        log.info("Ganador de tu lista: @%s en %s", name or w.display, w.title)
        if not self.webhook:
            return
        payload = {"content": content, "allowed_mentions": {"parse": [], "users": [w.discord_id]}}
        req = urllib.request.Request(self.webhook, data=json.dumps(payload).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
        try:
            urllib.request.urlopen(req, timeout=15).close()
        except Exception as exc:
            log.warning("No se pudo avisar del ganador en Discord: %s", exc)


def _local(iso: str | None) -> datetime:
    try:
        return datetime.fromisoformat((iso or "").replace("Z", "+00:00")).astimezone()
    except ValueError:
        return datetime.now()
