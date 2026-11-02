"""Transcripciones SINTÉTICAS (inventadas) de unos minutos alrededor de una ronda de sorteo.

Imitan la forma que da Whisper en vivo (un segmento por pausa, sin apenas puntuación) y los casos difíciles
que aparecen en la práctica: hablar de la contraseña antes de decirla, "la pass es" transcrito como
"la paz es", palabras mal oídas, "sorteo de las cajas: X" sin decir "contraseña" y frases posteriores que
parecen contraseñas. Sirven para detectar regresiones: la contraseña buena tiene que salir la primera.
"""

import re
from pathlib import Path

import pytest

from raffle_listener.extract import extract
from raffle_listener.transcript import Segment

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> list[Segment]:
    segments = []
    for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines():
        m = re.match(r"\[(\d+):(\d+):(\d+)\] (.*)", line)
        if m:
            h, mi, s, text = m.groups()
            t = int(h) * 3600 + int(mi) * 60 + int(s)
            segments.append(Segment(t, t + 1, text))
    return segments


@pytest.mark.parametrize(
    "fixture, typed, said_at",
    [
        ("ronda_sintetica_1.txt", "girasolenlamochila", "0:15:17"),  # "contraseña · girasol en la mochila · todo junto"
        ("ronda_sintetica_2.txt", "Tormenta", "0:30:05"),            # "La contraseña es · Tormenta · ¡Tormenta!"
        ("ronda_sintetica_3.txt", "Faro", "0:50:21"),                # "La paz es · Faro" (y no "haro" ni "Cuarto")
        ("ronda_sintetica_4.txt", "niebla", "1:20:24"),              # "La paz es niebla" (y no "Siempre")
        ("ronda_sintetica_5.txt", "Bombilla", "0:40:35"),            # "Sortido de las cajas Bombilla" x2
    ],
)
def test_finds_the_password_first(fixture, typed, said_at):
    # Solo cuenta la primera: el bot confirma una contraseña por ronda y deja de escuchar.
    candidates = extract(load(fixture))
    assert candidates[0].typed == typed
    h, m, s = map(int, said_at.split(":"))
    assert candidates[0].time == h * 3600 + m * 60 + s
