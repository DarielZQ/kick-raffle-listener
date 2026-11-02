"""Extractor por reglas: busca frases tipo "la contraseña es X" y puntúa las candidatas.

No tiene dependencias externas para que sea fácil de probar y de ajustar con ejemplos
(ver `tests/fixtures/`, transcripciones sintéticas con la forma que da Whisper).
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass

from ..transcript import Segment

MAX_WORDS = 4
LOOKAROUND_CHARS = 80
# Whisper corta los segmentos en las pausas: se tratan como un signo de puntuación más.
SEGMENT_JOINER = " · "

_NOUN_WORDS = r"contrase[ñn]as?|claves?|palabra(?:\s+clave)?|password|pass|c[oó]digo|keyword"
_NOUN = rf"(?:{_NOUN_WORDS})"
_QUALIFIER = r"(?:\s+(?:del?\s+(?:raffle|sorteo|rifa|giveaway|hoy)|de\s+hoy|secreta|m[aá]gica))?"
_VERB = r"(?:es|ser[aá]|va\s+a\s+ser|queda|era)"
# Whisper oye a menudo "la pass es X" como "la paz es X". "Paz" es palabra corriente, así que
# solo cuenta en los patrones fuertes ("la paz es X", "la paz: X"), nunca en "paz, X".
_NOUN_STRONG = rf"(?:{_NOUN_WORDS}|paz|pas)"

# (nombre, regex, peso, dirección): "after" = la contraseña va detrás del match, "before" = delante.
_PATTERNS: list[tuple[str, re.Pattern[str], float, str]] = [
    ("la_contraseña_es", re.compile(rf"\b{_NOUN_STRONG}{_QUALIFIER}\s+{_VERB}\b", re.I), 0.9, "after"),
    ("contraseña_dos_puntos", re.compile(rf"\b{_NOUN_STRONG}{_QUALIFIER}\s*:", re.I), 0.85, "after"),
    # Sin "clave" ("la paciencia es la clave") ni "era" ("uno más era la clave, bro", hablando del slot).
    ("x_es_la_contraseña", re.compile(r"\b(?:es|ser[aá])\s+(?:la|el|nuestra|nuestro)\s+"
                                      r"(?:contrase[ñn]a|password|palabra(?:\s+clave)?|c[oó]digo)\b", re.I), 0.75, "before"),
    # "Contraseña, girasol en la mochila" / "Contraseña · Faro": lo más habitual en los directos.
    ("contraseña_x", re.compile(rf"\b{_NOUN}{_QUALIFIER}\b", re.I), 0.7, "after"),
    # "Sorteo de las cajas: Bombilla" (Whisper: "Sortido de las cajas Bombilla"): sin decir "contraseña".
    ("sorteo_cajas_x", re.compile(r"\bsort(?:eo|ido)\s+de\s+(?:las\s+)?cajas\b", re.I), 0.7, "after"),
    ("pongan_x", re.compile(r"\b(?:pongan|escriban|metan|tecleen|copien)\b", re.I), 0.5, "after"),
]
_WEAK = {"contraseña_x", "sorteo_cajas_x", "pongan_x"}

# A quién se habla: se salta al principio y corta la captura después.
_VOCATIVES = {"chavales", "chicos", "chicas", "gente", "chat", "bro", "tío", "tio", "hermano", "señores", "peña"}
# Muletillas que se saltan antes de la contraseña ("la clave es, eh, murciélago").
_FILLERS = {"eh", "ehh", "em", "emm", "mm", "ah", "pues", "bueno", "o", "sea", "literal", "literalmente",
            "este"} | _VOCATIVES
# Palabras que cortan la captura cuando no son la primera.
_STOPS = {"no", "pero", "ok", "okey", "okay", "vale", "eh", "repito", "ya", "porque", "entonces", "bueno",
          "que", "pongan", "escriban", "listo", "para", "vamos", "todo", "junto", "raffle", "sorteo",
          "cajas", "caja"} | _VOCATIVES
# Conectores que no pueden quedar al final ("patata y" → "patata").
_TRAILING = {"y", "o", "de", "del", "con", "a", "al", "en", "la", "el", "los", "las", "un", "una"}
# Primeras palabras que indican que no es una contraseña.
_BAD_FIRST = {"para", "por", "en", "con", "de", "del", "a", "al", "que", "qué", "como", "cómo", "muy", "no",
              "si", "sí", "igual", "super", "súper", "bastante", "importante", "obligatoria", "necesaria",
              # Adverbios: "puede decir la contraseña · Siempre · pero en los últimos 10 s".
              "siempre", "nunca", "jamás", "jamas", "ahora", "luego", "después", "despues", "antes", "también",
              "tambien", "tampoco", "todavía", "todavia", "aún", "aun", "mañana", "hoy", "ayer", "pronto",
              "tarde", "casi", "solo", "sólo", "más", "mas", "menos", "mucho", "poco", "así", "asi", "otra",
              "otro", "cada", "ningún", "ninguna", "ninguno"}
# Para patrones débiles (sin "es"), además artículos, pronombres y verbos que siguen a "contraseña".
_BAD_FIRST_WEAK = _BAD_FIRST | {
    "la", "el", "los", "las", "lo", "le", "les", "se", "me", "te", "nos", "os", "un", "una", "esto", "eso",
    "esa", "ese", "algo", "su", "sus", "tu", "tus", "mi", "mis", "aquí", "aqui", "ahí", "ahi", "y", "o",
    "es", "era", "será", "sera", "va", "voy", "hay", "ponemos", "pongo", "ponéis", "poneis", "pon", "pones",
    "tenéis", "teneis", "tienes", "dije", "digo", "diré", "dire", "decid", "cualquier", "cualquiera",
    "nueva", "correcta", "incorrecta", "mal", "bien", "otra", "ponerla", "dicha"} | _STOPS
# Candidatas de una sola palabra que nunca son la contraseña.
_BAD_SINGLE = {"esa", "ese", "eso", "esta", "este", "esto", "aquella", "cual", "secreta", "fácil", "facil",
               "difícil", "dificil", "nueva", "misma", "igual", "la", "el", "lo", "obvia", "sencilla"}
# Risas e interjecciones que Whisper transcribe ("Contraseña. Ja, ja."): no cuentan como palabras.
_NOISE = re.compile(r"^(?:j[aeiou]|ha|he|ah|oh|eh|uh|mm+|hm+|buah|uf+|ay)+$", re.I)
# "…todo junto", "…sin espacios": se escribe sin espacios.
_JOINED = re.compile(r"^\W*(?:todo\s+)?(?:junto|juntos|pegado)\b|^\W*sin\s+espacios?\b", re.I)

# "es/era/fue la clave": uso predicativo, no "Contraseña: X".
_PREDICATE = re.compile(r"\b(?:es|era|fue|ser[aá]|ser[ií]a)\s+(?:la|el)\s+$", re.I)

_TOKEN = re.compile(r"[\w'’-]+|[^\w\s]")


@dataclass
class Candidate:
    text: str          # tal como se transcribió
    key: str           # normalizada (sin tildes, minúsculas) para agrupar
    score: float
    pattern: str
    time: float | None  # segundo de audio en que se dijo (la última vez)
    mentions: int
    context: str
    joined: bool = False  # dijeron "todo junto": se escribe sin espacios

    @property
    def typed(self) -> str:
        """Lo que conviene pegar en el raffle."""
        return variants(self.text, self.joined)[0]


def normalize(text: str) -> str:
    """Minúsculas, sin tildes, solo letras/números y espacios simples."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def variants(text: str, joined: bool = False) -> list[str]:
    """Formas de escribirla: tal cual, sin espacios, CamelCase, sin tildes (sin espacios primero si `joined`)."""
    words = text.split()
    nospace = "".join(words)
    out = [nospace.lower(), text] if joined else [text, nospace]
    out.append("".join(w[:1].upper() + w[1:] for w in words))
    out.append(normalize(text).replace(" ", ""))  # sin tildes ni mayúsculas
    return list(dict.fromkeys(out))


def _is_word(token: str) -> bool:
    return bool(re.match(r"[\w'’-]", token))


def _capture_after(rest: str) -> tuple[str, str]:
    """Devuelve (candidata, texto que sigue a la candidata)."""
    words: list[re.Match[str]] = []
    for m in _TOKEN.finditer(rest):
        tok = m.group()
        if not words:
            if not _is_word(tok) or tok.lower() in _FILLERS:
                continue  # saltar puntuación y muletillas iniciales
        elif not _is_word(tok) or tok.lower() in _STOPS:
            break
        words.append(m)
        if len(words) == MAX_WORDS:
            break
    while words and words[-1].group().lower() in _TRAILING:
        words.pop()
    if not words:
        return "", ""
    return " ".join(w.group() for w in words), rest[words[-1].end():]


def _capture_before(prev: str) -> str:
    words: list[str] = []
    for tok in reversed(_TOKEN.findall(prev)):
        if not words and not _is_word(tok):
            continue  # puntuación justo antes de "es la contraseña"
        if not _is_word(tok) or tok.lower() in _STOPS or tok.lower() in _FILLERS:
            break
        words.append(tok)
        if len(words) == MAX_WORDS:
            break
    words.reverse()
    while words and words[0].lower() in _TRAILING:
        words.pop(0)
    return " ".join(words)


def _valid(candidate: str, weak: bool) -> bool:
    words = candidate.lower().split()
    if not words or len(candidate) < 2:
        return False
    if words[0] in (_BAD_FIRST_WEAK if weak else _BAD_FIRST):
        return False
    if len(words) == 1 and words[0] in _BAD_SINGLE:
        return False
    if all(_NOISE.match(w) for w in words):
        return False
    if re.search(_NOUN, candidate, re.I):
        return False
    return True


def _join(segments: list[Segment]) -> tuple[str, list[int]]:
    parts: list[str] = []
    offsets: list[int] = []
    pos = 0
    for seg in segments:
        offsets.append(pos)
        parts.append(seg.text)
        pos += len(seg.text) + len(SEGMENT_JOINER)
    return SEGMENT_JOINER.join(parts), offsets


def extract(segments: list[Segment]) -> list[Candidate]:
    """Devuelve las candidatas a contraseña, de más a menos probable."""
    text, offsets = _join(segments)
    if not text.strip():
        return []
    norm_text = normalize(text)

    def time_at(pos: int) -> float:
        return segments[bisect_right(offsets, pos) - 1].start

    groups: dict[str, Candidate] = {}
    for name, regex, weight, direction in _PATTERNS:
        for m in regex.finditer(text):
            if name in _WEAK and _PREDICATE.search(text[max(0, m.start() - 20): m.start()]):
                continue  # "…era la clave, bro. Uno más": la palabra describe algo, no presenta la contraseña
            after = ""
            if direction == "after":
                cand, after = _capture_after(text[m.end(): m.end() + LOOKAROUND_CHARS])
            else:
                cand = _capture_before(text[max(0, m.start() - LOOKAROUND_CHARS): m.start()])
            if not _valid(cand, weak=name in _WEAK):
                continue
            key = normalize(cand)
            if not key:
                continue
            t = time_at(m.start())
            ctx = text[max(0, m.start() - 40): m.end() + 60].strip()
            joined = bool(_JOINED.search(after))
            prev = groups.get(key)
            if prev is None or weight > prev.score:
                groups[key] = Candidate(cand, key, weight, name, t, 0, ctx, joined)
            if prev is not None:
                groups[key].time = max(t, prev.time or t)
                groups[key].joined = groups[key].joined or prev.joined or joined

    for cand in groups.values():
        cand.mentions = max(1, len(re.findall(rf"(?<!\S){re.escape(cand.key)}(?!\S)", norm_text)))
        cand.score = round(min(0.99, cand.score + 0.1 * (cand.mentions - 1)), 2)

    # Empate (p. ej. ambas en 0.99): gana la que más se repite ("La paz es faro… faro, F-A, faro" frente a
    # un "haro" mal oído), y si no, la más reciente.
    return sorted(groups.values(), key=lambda c: (c.score, c.mentions, c.time or 0), reverse=True)
