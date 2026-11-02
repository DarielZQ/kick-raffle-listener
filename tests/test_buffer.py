import numpy as np

from raffle_listener.audio.buffer import AudioRingBuffer


def test_read_back_written_audio():
    buf = AudioRingBuffer(seconds=1, sample_rate=10)
    buf.write(np.arange(5, dtype=np.float32))
    audio, start = buf.read(0)
    assert start == 0
    assert audio.tolist() == [0, 1, 2, 3, 4]
    assert buf.now == 0.5


def test_wraparound_keeps_latest_and_reports_real_start():
    buf = AudioRingBuffer(seconds=1, sample_rate=10)  # capacidad 10 muestras
    buf.write(np.arange(7, dtype=np.float32))
    buf.write(np.arange(7, 14, dtype=np.float32))
    audio, start = buf.read(0)  # pide desde 0, pero solo quedan las 10 últimas
    assert start == 0.4
    assert audio.tolist() == list(range(4, 14))
    window, start = buf.read(1.0, 1.2)
    assert start == 1.0
    assert window.tolist() == [10, 11]


def test_empty_read():
    buf = AudioRingBuffer(seconds=1, sample_rate=10)
    audio, _ = buf.read(5, 6)
    assert len(audio) == 0
