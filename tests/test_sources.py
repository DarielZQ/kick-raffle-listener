"""El vigilante de audio: un stream que se queda colgado sin cerrarse debe reconectarse."""

import subprocess
import sys
import threading
import time

from raffle_listener.audio import sources
from raffle_listener.audio.sources import KickSource

# "streamlink" falso: manda 0,5 s de audio y se queda colgado con la salida abierta.
FAKE_STREAMLINK = [sys.executable, "-c",
                   "import sys, time; sys.stdout.buffer.write(b'\\x00' * 16000); sys.stdout.flush(); time.sleep(60)"]
# "ffmpeg" falso: copia la entrada a la salida tal cual.
FAKE_FFMPEG = [sys.executable, "-c",
               "import sys\nr, w = sys.stdin.buffer, sys.stdout.buffer\n"
               "while True:\n    d = r.read1(4096)\n    if not d: break\n    w.write(d); w.flush()"]


def test_reconnects_when_stream_hangs(monkeypatch):
    launched = []
    real_popen = subprocess.Popen

    def counting_popen(cmd, **kw):
        launched.append(cmd)
        return real_popen(cmd, **kw)

    monkeypatch.setattr(sources.subprocess, "Popen", counting_popen)
    src = KickSource("canal_ejemplo", stall_s=1, reconnect_s=0.1)
    monkeypatch.setattr(src, "commands", lambda: (FAKE_STREAMLINK, FAKE_FFMPEG))

    chunks = []
    stop = threading.Event()
    t = threading.Thread(target=src.run, args=(chunks.append, stop), daemon=True)
    t.start()
    deadline = time.monotonic() + 15
    while len(launched) < 4 and time.monotonic() < deadline:  # 2 procesos por conexión
        time.sleep(0.1)
    stop.set()
    src.restart("fin del test")
    t.join(timeout=10)

    assert len(launched) >= 4, "no reconectó tras quedarse sin audio"
    assert sum(len(c) for c in chunks) >= 8000  # recibió el audio antes de colgarse


def test_restart_without_connection_is_harmless():
    KickSource("canal_ejemplo").restart("nada que reiniciar")


def test_waits_quietly_while_offline_and_connects_when_stream_starts(monkeypatch, tmp_path, caplog):
    # Arrancar el bot horas antes del directo: un solo aviso de espera y conexión automática al empezar.
    counter = tmp_path / "intentos"
    fake_streamlink = [sys.executable, "-c",
                       "import sys, time, pathlib\n"
                       f"p = pathlib.Path(r'{counter}')\n"
                       "n = int(p.read_text()) + 1 if p.exists() else 1\n"
                       "p.write_text(str(n))\n"
                       "if n <= 2:\n"
                       "    sys.stderr.write('error: No playable streams found on this URL\\n'); sys.exit(1)\n"
                       "sys.stdout.buffer.write(b'\\x00' * 16000); sys.stdout.flush(); time.sleep(60)"]
    src = KickSource("canal_ejemplo", stall_s=30, reconnect_s=0.2)
    monkeypatch.setattr(src, "commands", lambda: (fake_streamlink, FAKE_FFMPEG))

    chunks = []
    stop = threading.Event()
    with caplog.at_level("INFO", logger="raffle_listener.audio.sources"):
        t = threading.Thread(target=src.run, args=(chunks.append, stop), daemon=True)
        t.start()
        deadline = time.monotonic() + 15
        while not chunks and time.monotonic() < deadline:
            time.sleep(0.1)
        stop.set()
        src.restart("fin del test")
        t.join(timeout=10)

    messages = [r.getMessage() for r in caplog.records]
    assert sum("no está en marcha" in m for m in messages) == 1
    assert any("Ha empezado el directo" in m for m in messages)
    assert not any("No playable streams" in m for m in messages)  # el error de streamlink no ensucia la consola
    assert not any("Invalid data" in m for m in messages)  # ni el de ffmpeg
    assert chunks
