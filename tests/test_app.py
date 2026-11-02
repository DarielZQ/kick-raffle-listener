import math

from raffle_listener.app import App
from raffle_listener.config import Config
from raffle_listener.extract import Candidate


def cand(text: str, score: float = 0.9) -> Candidate:
    return Candidate(text, text, score, "contraseña_x", 0.0, 1, "…")


class FakeNotifier:
    def __init__(self):
        self.alerts = []

    def alert(self, candidates, reason, provisional=False):
        self.alerts.append((candidates[0].text, provisional))

    def info(self, message):
        pass


def make_app() -> App:
    cfg = Config()
    cfg.buffer.audio_seconds = 1
    app = App(cfg)
    app.notifier = FakeNotifier()
    app._active_until = math.inf  # ronda abierta
    return app


def test_one_confirmed_password_per_round_then_stops_listening():
    # Caso típico: tras confirmar "llave", una revisión posterior saca "uno más" (se habla de otra cosa).
    app = make_app()
    app._report([cand("llave")], "revisión", confirmed=True)
    app._report([cand("uno más", 0.95)], "revisión", confirmed=True)
    app._report([cand("otra")], "en vivo", confirmed=False)
    assert app.notifier.alerts == [("llave", False)]
    assert not app._transcribing()  # deja de transcribir hasta la próxima ronda


def test_provisional_then_confirmed():
    app = make_app()
    app._report([cand("llave", 0.7)], "en vivo", confirmed=False)
    app._report([cand("llave", 0.7)], "en vivo", confirmed=False)  # repetido: no vuelve a avisar
    app._report([cand("llave", 0.8)], "revisión", confirmed=True)
    assert app.notifier.alerts == [("llave", True), ("llave", False)]


def test_new_round_listens_again():
    app = make_app()
    app._report([cand("llave")], "revisión", confirmed=True)
    app._new_round()
    assert app._transcribing()
    app._report([cand("cuarto")], "revisión", confirmed=True)
    assert [a[0] for a in app.notifier.alerts] == ["llave", "cuarto"]


def test_below_threshold_is_ignored():
    app = make_app()
    app._report([cand("pepino", 0.5)], "revisión", confirmed=True)
    assert app.notifier.alerts == []


class FakeSource:
    def __init__(self):
        self.restarts = []

    def restart(self, reason):
        self.restarts.append(reason)


def test_round_open_without_audio_reconnects_and_warns():
    # La ronda se abre con el audio de Kick colgado desde hace minutos.
    app = make_app()
    infos = []
    app.notifier.info = infos.append
    app.source = FakeSource()
    app._check_audio()  # nunca ha llegado audio
    assert app.source.restarts and "nunca" in app.source.restarts[0]
    assert any("OJO" in m for m in infos)


def test_round_open_with_fresh_audio_does_nothing():
    import numpy as np

    app = make_app()
    app.source = FakeSource()
    app.buffer.write(np.zeros(160, dtype=np.float32))
    app._check_audio()
    assert app.source.restarts == []
