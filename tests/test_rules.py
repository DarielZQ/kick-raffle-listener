import pytest

from raffle_listener.extract import extract, normalize, variants
from raffle_listener.transcript import Segment


def segs(*texts: str, step: float = 5.0) -> list[Segment]:
    return [Segment(i * step, i * step + step, t) for i, t in enumerate(texts)]


def best(*texts: str) -> str | None:
    cands = extract(segs(*texts))
    return cands[0].text if cands else None


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Bueno chicos, la contraseña es patata de papa, no la digan en el stream.", "patata de papa"),
        ("la contraseña es patata de papa no la digan en el stream", "patata de papa"),
        ("El código del sorteo es: dragón rojo.", "dragón rojo"),
        ("Patata de papa es la contraseña, ¿vale?", "Patata de papa"),
        ("bueno patata de papa es la contraseña", "patata de papa"),
        ("La clave es, eh, murciélago.", "murciélago"),
        ("contraseña: Luna llena", "Luna llena"),
        ("la palabra clave de hoy es “tortilla”, ok?", "tortilla"),
        ("la contraseña es sal y pimienta, no la pongan en el chat", "sal y pimienta"),
        ("la contraseña es patata y no la digan", "patata"),
        ("Pongan pepino en el raffle", "pepino"),
        ("Abierto el sorteo de cajas · La paz es niebla · Niebla la paz", "niebla"),  # Whisper: "pass" → "paz"
        ("la pass es niebla", "niebla"),
        ("Sortido de las cajas Bombilla · Chavales, sortido de las cajas Bombilla", "Bombilla"),
        ("La contraseña, llave. Contraseña, llave. Buena contraseña, eh. Un momento aquí.", "llave"),
    ],
)
def test_extracts_password(text, expected):
    assert best(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "pongan la contraseña en el raffle",
        "esa es la contraseña",
        "la contraseña es secreta, no la digan",
        "la contraseña es muy fácil",
        "el código es para el raffle de mañana",
        "hoy jugamos un rato y luego vemos",
        "Contraseña. · Ja, ja.",                       # en vivo: risa tras "Contraseña"
        "¿Qué contraseña ponemos para las cajas?",      # se habla de la contraseña
        "la contraseña la voy a hacer 100%",
        "Contraseña, pero la voy a decir al final",     # en vivo
        # hablando de otra cosa ("uno más" no es la contraseña):
        "Esto está muy, muy bien, eh. Ah, se ha pasado. Uno más, bro. Uno más era la clave, bro. Uno más el 12.",
        "la paciencia es la clave",
        # "siempre" no es la contraseña:
        "En los últimos 10 segundos puede decir la contraseña · Siempre · Pero tiene que ser en los últimos 10 segundos, ¿vale?",
        "la paz sea contigo",
        "Abierto el sorteo de cajas · Vamos a ver qué sale",
        "el sorteo de las cajas en directo lo tenéis aquí",
        "queremos la paz, hermano",
        "",
    ],
)
def test_no_false_positives(text):
    assert best(text) is None


def test_phrase_split_across_segments():
    cands = extract(segs("ojo que la contraseña es", "patata de papa. Repito, patata de papa."))
    assert cands[0].text == "patata de papa"
    assert cands[0].mentions == 2
    assert cands[0].score > 0.9
    assert cands[0].time == 0.0


def test_repetition_raises_weak_pattern():
    once = extract(segs("pongan pepino"))[0]
    twice = extract(segs("pongan pepino.", "pepino, pepino"))[0]
    assert twice.score > once.score


def test_strong_pattern_beats_weak():
    cands = extract(segs("pongan algo bonito", "la contraseña es caracol azul"))
    assert cands[0].text == "caracol azul"


def test_normalize_and_variants():
    assert normalize("  Dragón ROJO! ") == "dragon rojo"
    assert variants("patata de papa") == ["patata de papa", "patatadepapa", "PatataDePapa"]
    assert variants("Dragón rojo", joined=True) == ["dragónrojo", "Dragón rojo", "DragónRojo", "dragonrojo"]
