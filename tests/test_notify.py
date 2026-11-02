import json

import pytest

from raffle_listener import notify
from raffle_listener.config import OutputConfig
from raffle_listener.extract import Candidate


@pytest.fixture
def sent(monkeypatch):
    calls = []

    class Resp:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        calls.append((req.full_url, json.loads(req.data), req.get_header("User-agent")))
        return Resp()

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)

    class SyncThread:  # ejecutar el envío en el mismo hilo para poder comprobarlo
        def __init__(self, target, args, daemon):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(notify.threading, "Thread", SyncThread)
    return calls


def make(webhook="https://discord.test/hook", **kw):
    cfg = OutputConfig(clipboard=False, toast=False, beep=False, discord_webhook=webhook, **kw)
    return notify.Notifier(cfg)


CAND = Candidate("girasol en la mochila", "girasol en la mochila", 0.99, "contraseña_x", 1.0, 3, "…", joined=True)


def test_confirmed_password_goes_to_discord(sent):
    make().alert([CAND], "revisión")
    assert sent == [("https://discord.test/hook",
                     {"content": "Contraseña del sorteo: girasolenlamochila"}, "raffle-listener/0.1")]


def test_provisional_is_not_sent_by_default(sent):
    make().alert([CAND], "en vivo", provisional=True)
    assert sent == []
    make(discord_provisional=True).alert([CAND], "en vivo", provisional=True)
    assert len(sent) == 1


def test_no_webhook_no_request(sent):
    make(webhook="").alert([CAND], "revisión")
    assert sent == []
