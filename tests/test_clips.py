import json
import math
import subprocess
import threading
import time

import numpy as np
import pytest

from raffle_listener import clips
from raffle_listener.audio.buffer import AudioRingBuffer
from raffle_listener.clips import ClipRecorder, DiscordClips, encode_mp3
from raffle_listener.config import ClipConfig

SR = 16_000


def tone(seconds: float, start: float = 0.0) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR + start
    return (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


def mp3_seconds(data: bytes) -> float:
    pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", str(SR),
                          "pipe:1"], input=data, capture_output=True, check=True).stdout
    return len(pcm) / 2 / SR


def test_encode_mp3_in_memory():
    data = encode_mp3(tone(3), SR, "48k")
    assert data[:3] == b"ID3" or data[0] == 0xFF
    assert abs(mp3_seconds(data) - 3) < 0.2


def test_clip_window_is_before_and_after_the_opening():
    buf = AudioRingBuffer(60)
    buf.write(tone(30))
    rec = ClipRecorder(ClipConfig(before_seconds=20, after_seconds=7, stream_delay_seconds=0), buf, None)
    data, seconds = rec.build(at=22)  # de 2 s a 29 s
    assert seconds == pytest.approx(27, abs=0.01)
    assert abs(mp3_seconds(data) - 27) < 0.2


def test_clip_waits_for_audio_still_arriving():
    buf = AudioRingBuffer(60)
    buf.write(tone(5))
    rec = ClipRecorder(ClipConfig(before_seconds=2, after_seconds=3, stream_delay_seconds=0), buf, None)

    def late_audio():
        time.sleep(0.8)
        buf.write(tone(4))

    threading.Thread(target=late_audio).start()
    t0 = time.monotonic()
    _, seconds = rec.build(at=5)  # necesita audio hasta el segundo 8
    assert time.monotonic() - t0 >= 0.7
    assert seconds == pytest.approx(5, abs=0.01)


class FakeHTTP:
    def __init__(self):
        self.requests = []

    def __call__(self, req, timeout):
        self.requests.append((req.get_method(), req.full_url, req.data, dict(req.header_items())))
        body = json.dumps({"id": "123456"}).encode() if req.get_method() == "POST" else b""

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, *a):
                return body

            def close(self):
                pass

        return Resp()


@pytest.fixture
def http(monkeypatch):
    fake = FakeHTTP()
    monkeypatch.setattr(clips.urllib.request, "urlopen", fake)
    return fake


def test_upload_sends_the_mp3_and_returns_the_message_id(http):
    d = DiscordClips("https://discord.test/api/webhooks/1/abc")
    mid = d.upload([("raffle.mp3", b"ID3normal"), ("raffle-x2.mp3", b"ID3rapido")], "Clip del sorteo")
    method, url, body, headers = http.requests[0]
    assert (method, url, mid) == ("POST", "https://discord.test/api/webhooks/1/abc?wait=true", "123456")
    assert b'name="files[0]"; filename="raffle.mp3"' in body and b"ID3normal" in body
    assert b'name="files[1]"; filename="raffle-x2.mp3"' in body and b"ID3rapido" in body
    assert b'"attachments": [{"id": 0, "filename": "raffle.mp3"}, {"id": 1, "filename": "raffle-x2.mp3"}]' in body
    assert b"Clip del sorteo" in body
    assert headers["Content-type"].startswith("multipart/form-data; boundary=")


def test_x2_copy_is_half_as_long():
    data = encode_mp3(tone(10), SR, "48k", speed=2.0)
    assert abs(mp3_seconds(data) - 5) < 0.2


def test_clip_files_normal_and_x2():
    buf = AudioRingBuffer(60)
    buf.write(tone(30))
    rec = ClipRecorder(ClipConfig(before_seconds=5, after_seconds=5, stream_delay_seconds=0), buf, None)
    files = rec.files(rec.collect(at=20))
    assert [n.split("-")[-1] for n, _ in files][1] == "x2.mp3" and len(files) == 2
    assert abs(mp3_seconds(files[0][1]) - 10) < 0.2 and abs(mp3_seconds(files[1][1]) - 5) < 0.2
    no_copies = ClipRecorder(ClipConfig(before_seconds=5, after_seconds=5, speed_copies=[]), buf, None)
    assert len(no_copies.files(no_copies.collect(at=20))) == 1


def test_message_is_deleted_after_the_delay_and_on_exit(http):
    d = DiscordClips("https://discord.test/api/webhooks/1/abc")
    d.schedule_delete("111", 0.2)
    d.schedule_delete("222", 60)
    time.sleep(0.6)
    assert ("DELETE", "https://discord.test/api/webhooks/1/abc/messages/111") in [r[:2] for r in http.requests]
    d.flush()  # al cerrar el bot: el que faltaba se borra ya
    assert ("DELETE", "https://discord.test/api/webhooks/1/abc/messages/222") in [r[:2] for r in http.requests]


def test_full_clip_goes_to_discord_without_writing_files(http, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    buf = AudioRingBuffer(60)
    buf.write(tone(12))
    cfg = ClipConfig(before_seconds=2, after_seconds=3, stream_delay_seconds=0, delete_after_minutes=0.005)
    rec = ClipRecorder(cfg, buf, DiscordClips("https://discord.test/api/webhooks/1/abc"))
    rec.capture("prueba", at=6).join(timeout=15)
    time.sleep(0.8)  # 0,3 s de espera para borrar
    assert [r[0] for r in http.requests] == ["POST", "DELETE"]
    assert b"-x2.mp3" in http.requests[0][2]  # el normal y el x2 van en el mismo mensaje (y se borran juntos)
    assert list(tmp_path.iterdir()) == []  # nada en disco


def test_one_clip_per_round_even_if_both_sections_open():
    from raffle_listener.app import App
    from raffle_listener.config import Config
    from raffle_listener.triggers.site_poller import RaffleEvent

    cfg = Config()
    cfg.buffer.audio_seconds = 1
    cfg.trigger.transcribe = "off"
    app = App(cfg)
    captured = []
    app.clips.capture = lambda reason, at=None, message=None: captured.append((reason, message))
    app.notifier.info = lambda m: None
    app._on_raffle_open(RaffleEvent("a", "cajas", "no_subs", "open", True))
    app._on_raffle_open(RaffleEvent("b", "cajas", "subs", "open", True))
    assert len(captured) == 1 and "no_subs" in captured[0][0]
    assert captured[0][1].startswith("Clip del sorteo")
    assert math.isinf(app._active_until)
    # Un Guess que se abre a la vez tiene su propio clip, marcado en mayúsculas.
    app._on_raffle_open(RaffleEvent("g", "guess", "¿Cuánto paga el bonus?", "active", True))
    assert len(captured) == 2 and captured[1][1].startswith("GUESS")
