"""Configuración: config.toml → dataclasses con valores por defecto.

Los valores que dependen del canal o del sitio (canal de Kick, URL de la API de estado, página del sorteo,
textos del widget) no tienen valor por defecto: hay que ponerlos en `config.toml`. `missing_settings` dice
cuáles faltan para que el arranque falle con un mensaje claro.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from urllib.parse import urlparse


@dataclass
class StreamConfig:
    source: str = "kick"
    channel: str = ""  # nombre del canal de Kick (obligatorio con source = "kick")
    quality: str = "worst"


@dataclass
class SttConfig:
    model: str = "large-v3-turbo"
    device: str = "cuda"
    compute_type: str = "int8_float16"
    language: str = "es"
    step_seconds: float = 3.0
    holdback_seconds: float = 1.5
    max_window_seconds: float = 25.0


@dataclass
class BufferConfig:
    audio_seconds: float = 300
    transcript_seconds: float = 600


@dataclass
class ExtractConfig:
    window_seconds: float = 90
    min_score: float = 0.8
    min_score_raffle: float = 0.6


@dataclass
class TriggerConfig:
    transcribe: str = "raffle"  # "raffle": solo con ronda abierta · "always": siempre · "off": sin Whisper
    hotkey: str = "<ctrl>+<alt>+p"
    hotkey_seconds: float = 300
    reanalyze_seconds: float = 60
    review_every_seconds: float = 30
    review_window_seconds: float = 60
    listen_after_seconds: float = 30
    site_url: str = ""  # API JSON con el estado público de los sorteos; "" = no vigilar el sitio
    site_interval_seconds: float = 3.0


@dataclass
class OutputConfig:
    clipboard: bool = True
    toast: bool = True
    beep: bool = True
    discord_webhook: str = ""
    discord_message: str = "Contraseña del sorteo: "
    discord_provisional: bool = False


@dataclass
class ClipConfig:
    enabled: bool = True
    before_seconds: float = 20
    after_seconds: float = 70
    stream_delay_seconds: float = 8  # lo que tarda el audio de Kick respecto a la web
    delete_after_minutes: float = 15
    bitrate: str = "48k"
    speed_copies: list[float] = field(default_factory=lambda: [2.0])  # además del normal, copias aceleradas
    message: str = ("Clip del sorteo (20 s antes y 70 s después de abrirse; el archivo x2 es el mismo audio "
                    "al doble de velocidad). Se borra en 15 min.")
    message_guess: str = ("GUESS · Clip del Guess (20 s antes y 70 s después de abrirse; el archivo x2 es el "
                          "mismo audio al doble de velocidad). Se borra en 15 min.")


@dataclass
class WinnersConfig:
    enabled: bool = True
    usernames: list[str] = field(default_factory=list)  # @ de Discord (o IDs numéricos) a vigilar
    message: str = "{mention} ¡has ganado! · Dónde: {sorteo}{premio} · {fecha} a las {hora}"
    rounds_title: str = "Cajas ({section})"  # nombre con el que se anuncian las rondas por secciones


@dataclass
class AutoJoinConfig:
    enabled: bool = False
    page_url: str = ""               # página del sitio con el formulario del sorteo
    widget_text: str = ""            # texto que identifica el bloque (<section>) del sorteo en la página
    join_path: str = ""              # ruta de la petición POST que envía la contraseña (p. ej. /api/…/join)
    password_placeholder: str = "Contraseña del sorteo"
    submit_text: str = "Participar en"  # el botón de enviar empieza por este texto
    login_text: str = "Iniciar sesión"  # botón que solo aparece sin sesión
    sections: list[str] = field(default_factory=lambda: ["No Subs", "Subs"])
    max_attempts: int = 3
    profile_dir: str = ".browser"
    browser_channel: str = "chrome"
    headless: bool = False
    start_minimized: bool = True


@dataclass
class Config:
    stream: StreamConfig = field(default_factory=StreamConfig)
    stt: SttConfig = field(default_factory=SttConfig)
    buffer: BufferConfig = field(default_factory=BufferConfig)
    extract: ExtractConfig = field(default_factory=ExtractConfig)
    trigger: TriggerConfig = field(default_factory=TriggerConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    autojoin: AutoJoinConfig = field(default_factory=AutoJoinConfig)
    clip: ClipConfig = field(default_factory=ClipConfig)
    winners: WinnersConfig = field(default_factory=WinnersConfig)


def load_config(path: str | Path) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    cfg = Config()
    for section in fields(Config):
        values = raw.get(section.name, {})
        target = getattr(cfg, section.name)
        known = {f.name for f in fields(target)}
        unknown = set(values) - known
        if unknown:
            raise ValueError(f"Claves desconocidas en [{section.name}]: {', '.join(sorted(unknown))}")
        for key, value in values.items():
            setattr(target, key, value)
    if cfg.trigger.transcribe not in ("raffle", "always", "off"):
        raise ValueError(f"[trigger].transcribe debe ser 'raffle', 'always' u 'off', no {cfg.trigger.transcribe!r}")
    return cfg


def is_placeholder(value: str) -> bool:
    """Vacío o un marcador de `config.example.toml` (`<canal>`, `https://sitio.example/…`)."""
    value = (value or "").strip()
    if not value or "<" in value or ">" in value:
        return True
    host = urlparse(value).hostname or ""
    return host == "example" or host.endswith(".example")


def missing_settings(cfg: Config, *, login: bool = False) -> list[str]:
    """Valores que faltan en `config.toml` para arrancar (o para `--login`)."""
    missing: list[str] = []
    autojoin = cfg.autojoin.enabled and cfg.trigger.transcribe != "off"
    if login or autojoin:
        if is_placeholder(cfg.autojoin.page_url):
            missing.append("[autojoin].page_url: URL de la página del sitio donde está el formulario del sorteo")
    if login:
        return missing
    if cfg.stream.source == "kick" and is_placeholder(cfg.stream.channel):
        missing.append("[stream].channel: nombre del canal de Kick que se escucha")
    if cfg.trigger.site_url and is_placeholder(cfg.trigger.site_url):
        missing.append('[trigger].site_url: URL de la API de estado del sitio (o "" para no vigilarlo)')
    if autojoin:
        if is_placeholder(cfg.autojoin.widget_text):
            missing.append("[autojoin].widget_text: texto que identifica el bloque del sorteo en la página")
        if is_placeholder(cfg.autojoin.join_path):
            missing.append("[autojoin].join_path: ruta de la petición que envía la contraseña")
    return missing


def require_settings(cfg: Config, *, login: bool = False) -> None:
    """Sale con un error claro si faltan valores del canal o del sitio."""
    missing = missing_settings(cfg, login=login)
    if missing:
        lines = "\n".join(f"  - {m}" for m in missing)
        raise SystemExit(f"Faltan valores en config.toml (copia config.example.toml y rellénalos):\n{lines}")
