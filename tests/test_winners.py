"""Aviso de ganadores. Estructura del JSON de estado público que espera el bot, con datos inventados."""

import json

import pytest

from raffle_listener import winners
from raffle_listener.config import WinnersConfig
from raffle_listener.winners import WinnerWatcher, winners_in


def winner(discord_id, username, global_name, status="confirmed", prize=10):
    return {"id": f"w{discord_id}", "drawId": "d1", "discordId": discord_id, "displayName": global_name,
            "discordUsername": username, "discordGlobalName": global_name, "kickUserId": "1", "kickUsername": "k",
            "status": status, "generatedAt": "2026-01-15T17:32:17.550Z", "confirmedAt": "2026-01-15T17:33:32.644Z",
            "prizeUsd": prize}


def raffle_state(potential, confirmed=None, raffle_id="r1"):
    return {"ok": True, "guess": {"ok": True, "guess": None, "guesses": []}, "cajas": {"ok": True, "raffle": None},
            "raffles": {"ok": True, "raffles": [{
                "id": raffle_id, "title": "SORTEO DE PRUEBA - 5 GANADORES", "status": "active",
                "participationOpen": False, "passwordRequired": True,
                "potentialWinners": potential, "confirmedWinners": confirmed if confirmed is not None else [],
                "confirmedWinnerDiscordIds": [w["discordId"] for w in (confirmed or [])]}]}}


EMPTY = raffle_state([], raffle_id="r0")


class FakeHTTP:
    def __init__(self):
        self.sent = []

    def __call__(self, req, timeout):
        self.sent.append(json.loads(req.data))

        class R:
            def close(self):
                pass

        return R()


@pytest.fixture
def http(monkeypatch):
    fake = FakeHTTP()
    monkeypatch.setattr(winners.urllib.request, "urlopen", fake)
    return fake


def watcher(*usernames):
    return WinnerWatcher(WinnersConfig(usernames=list(usernames)), "https://discord.test/api/webhooks/1/abc")


def test_announces_watched_winner_with_real_mention(http):
    w = watcher("@UsuarioEjemplo1")
    w.on_state(EMPTY)  # arranque
    ejemplo1 = winner("111", "usuarioejemplo1", "Usuario Ejemplo ❄")
    w.on_state(raffle_state([ejemplo1], [ejemplo1]))
    assert len(http.sent) == 1
    msg = http.sent[0]
    assert msg["content"].startswith("<@111> ¡has ganado! · Dónde: SORTEO DE PRUEBA - 5 GANADORES · ")
    assert "Premio: 10 $" in msg["content"] and "15/01/2026" in msg["content"]
    assert msg["allowed_mentions"] == {"parse": [], "users": ["111"]}


def test_only_confirmed_winners_and_only_once(http):
    w = watcher("usuarioejemplo1")
    w.on_state(EMPTY)
    w.on_state(raffle_state([winner("111", "usuarioejemplo1", "UsuarioEjemplo1", status="pending")]))
    assert http.sent == []  # generado pero aún no confirmado: podría volver a sortearse
    confirmed = winner("111", "usuarioejemplo1", "UsuarioEjemplo1")
    w.on_state(raffle_state([confirmed], [confirmed]))
    w.on_state(raffle_state([confirmed], [confirmed]))
    assert len(http.sent) == 1


def test_winners_already_on_the_page_at_startup_are_not_announced(http):
    w = watcher("usuarioejemplo1")
    confirmed = winner("111", "usuarioejemplo1", "UsuarioEjemplo1")
    w.on_state(raffle_state([confirmed], [confirmed]))
    w.on_state(raffle_state([confirmed], [confirmed]))
    assert http.sent == []


def test_custom_display_name_is_not_used_for_matching(http):
    w = watcher("usuarioejemplo1")
    w.on_state(EMPTY)
    impostor = winner("222", "otra_persona", "usuarioejemplo1")  # se puso de nombre "usuarioejemplo1", pero su @ es otro
    w.on_state(raffle_state([impostor], [impostor]))
    assert http.sent == []


def test_numeric_id_in_the_list_works(http):
    w = watcher("333")
    w.on_state(EMPTY)
    x = winner("333", "alguien", "Alguien")
    w.on_state(raffle_state([x], [x]))
    assert len(http.sent) == 1


def test_cajas_winner_without_username_matched_through_known_id(http):
    w = watcher("usuarioejemplo1")
    ejemplo1 = winner("111", "usuarioejemplo1", "UsuarioEjemplo1")
    w.on_state(raffle_state([ejemplo1], [ejemplo1]))  # arranque: aprende que 111 = usuarioejemplo1
    cajas = raffle_state([ejemplo1], [ejemplo1])
    cajas["cajas"]["raffle"] = {"id": "c1", "rounds": [{"id": "round9", "section": "no_subs", "status": "drawn",
                                                        "winners": [{"discordId": "111", "displayName": "UsuarioEjemplo1",
                                                                     "kickUsername": "k", "status": "selected"}]}],
                                "winnerEntries": []}
    w.on_state(cajas)
    assert len(http.sent) == 1 and "Cajas (No Subs)" in http.sent[0]["content"]


def test_guess_winners_are_announced(http):
    w = watcher("usuarioejemplo1")
    w.on_state(EMPTY)
    st = raffle_state([], raffle_id="r0")
    st["guess"]["guesses"] = [{"id": "g1", "title": "¿Cuánto paga?", "status": "closed", "participationOpen": False,
                               "passwordRequired": True, "potentialWinners": [winner("111", "usuarioejemplo1", "UsuarioEjemplo1")]}]
    w.on_state(st)
    assert len(http.sent) == 1 and "Guess: ¿Cuánto paga?" in http.sent[0]["content"]


def test_does_nothing_without_usernames(http):
    w = watcher()
    w.on_state(EMPTY)
    x = winner("111", "usuarioejemplo1", "UsuarioEjemplo1")
    w.on_state(raffle_state([x], [x]))
    assert http.sent == []


def test_winners_in_reads_all_sources():
    st = raffle_state([winner("1", "a", "A")], [winner("1", "a", "A")])
    assert [(x.kind, x.username) for x in winners_in(st)] == [("raffle", "a")]
