"""Orquesta audio → transcripción → extracción → avisos, y los disparadores.

Con `transcribe = "raffle"` el audio entra siempre al buffer (barato), pero Whisper solo trabaja
mientras hay una ronda abierta en la web (más `listen_after_seconds`) o tras pulsar la tecla rápida.
Con `transcribe = "off"` no se carga Whisper: solo se manda el clip de cada ronda a Discord (`[clip]`).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Callable

from .audio.buffer import AudioRingBuffer
from .audio.sources import make_source
from .autojoin import AutoJoiner, JoinResult
from .clips import ClipRecorder, DiscordClips
from .winners import WinnerWatcher
from .config import Config
from .extract import Candidate, extract
from .notify import Notifier
from .stt.live import LiveTranscriber
from .stt.transcriber import Transcriber
from .transcript import Segment, Transcript
from .triggers.hotkey import Hotkey
from .triggers.site_poller import RaffleEvent, SitePoller

log = logging.getLogger(__name__)

TRIGGER_DEBOUNCE_S = 15  # no_subs y subs se abren a la vez: un solo re-análisis
AUDIO_STALE_S = 5        # al abrirse una ronda, si no llega audio desde hace más de esto, algo va mal


class App:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.buffer = AudioRingBuffer(cfg.buffer.audio_seconds)
        self.transcript = Transcript(cfg.buffer.transcript_seconds)
        self.notifier = Notifier(cfg.output)
        self.stop = threading.Event()
        self.transcriber: Transcriber | None = None
        self.source = None
        self._alerted: dict[str, float] = {}  # key → score con el que se avisó
        self._confirmed: str | None = None    # contraseña confirmada por la revisión precisa en esta ronda
        self._round_done = False              # ya hay contraseña confirmada: no escuchar hasta la próxima ronda
        self._active_until = 0.0              # time.monotonic(); inf mientras haya ronda abierta
        self._last_trigger = -math.inf
        self._last_clip: dict[str, float] = {}  # tipo ("cajas", "raffle", "guess") → última apertura con clip
        self._lock = threading.Lock()
        self.whisper_enabled = cfg.trigger.transcribe != "off"
        self.joiner = (AutoJoiner(cfg.autojoin, cfg.autojoin.page_url, self._on_join_result)
                       if cfg.autojoin.enabled and self.whisper_enabled else None)
        self.discord_clips = DiscordClips(cfg.output.discord_webhook) if cfg.output.discord_webhook else None
        self.clips = ClipRecorder(cfg.clip, self.buffer, self.discord_clips) if cfg.clip.enabled else None
        self.winners = WinnerWatcher(cfg.winners, cfg.output.discord_webhook)

    # --- ciclo de vida -------------------------------------------------------------------

    def run(self) -> None:
        source = self.source = make_source(self.cfg.stream)
        if self.whisper_enabled:
            log.info("Cargando Whisper '%s'…", self.cfg.stt.model)
            self.transcriber = Transcriber(self.cfg.stt)
            live = LiveTranscriber(self.transcriber, self.buffer, self.transcript, self.cfg.stt,
                                   self._on_commit, self._transcribing)
        elif self.cfg.autojoin.enabled:
            log.warning("Auto-entrada desactivada: necesita Whisper (transcribe = \"off\")")

        self._spawn("audio", source.run, self.buffer.write, self.stop)
        if self.whisper_enabled:
            self._spawn("stt", live.run, self.stop)
            self._spawn("review", self._review_loop)
        if self.joiner:
            self._spawn("autojoin", self.joiner.run, self.stop)
        if self.cfg.trigger.hotkey:
            self._spawn("hotkey", Hotkey(self.cfg.trigger.hotkey, self._on_hotkey).run, self.stop)
        if self.cfg.trigger.site_url:
            poller = SitePoller(self.cfg.trigger.site_url, self.cfg.trigger.site_interval_seconds,
                                self._on_raffle_open, self._on_raffle_closed, self.winners.on_state)
            if self.cfg.winners.enabled and self.cfg.winners.usernames:
                log.info("Aviso de ganadores activo para %d usuario(s) de Discord", len(self.cfg.winners.usernames))
            self._spawn("site", poller.run, self.stop)

        mode = {"raffle": "solo con ronda abierta", "always": "todo el directo", "off": "desactivada"}
        clip = (f"clip de {self.cfg.clip.before_seconds:.0f} s antes a {self.cfg.clip.after_seconds:.0f} s después"
                if self.clips else "sin clip")
        log.info("Escuchando (transcripción: %s · %s). Ctrl+C para salir.", mode[self.cfg.trigger.transcribe], clip)
        try:
            while not self.stop.wait(0.5):
                pass
        except KeyboardInterrupt:
            log.info("Saliendo…")
            self.stop.set()
        finally:
            if self.discord_clips:
                self.discord_clips.flush()  # no dejar clips en Discord si el bot se cierra antes de su hora

    def _spawn(self, name: str, target: Callable, *args) -> None:
        def guarded() -> None:
            try:
                target(*args)
            except Exception:
                log.exception("El hilo '%s' falló", name)
                self.stop.set()

        threading.Thread(target=guarded, name=name, daemon=True).start()

    # --- ventana activa ------------------------------------------------------------------

    @property
    def _raffle_active(self) -> bool:
        return not self._round_done and time.monotonic() < self._active_until

    def _transcribing(self) -> bool:
        return self.cfg.trigger.transcribe == "always" or self._raffle_active

    @property
    def _threshold(self) -> float:
        return self.cfg.extract.min_score_raffle if self._raffle_active else self.cfg.extract.min_score

    def _on_raffle_open(self, ev: RaffleEvent) -> None:
        new_round = time.monotonic() - self._last_trigger > TRIGGER_DEBOUNCE_S
        if new_round:
            self._new_round()
        self._active_until = math.inf
        self._check_audio()
        pw = "con contraseña" if ev.password_required else "sin contraseña"
        reason = f"ronda abierta ({ev.kind}/{ev.section}, {pw})"
        if self.clips and self._first_open_of_kind(ev.kind):  # no_subs y subs se abren a la vez: un solo clip
            message = self.cfg.clip.message_guess if ev.kind == "guess" else self.cfg.clip.message
            self.clips.capture(reason, message=message)
        self.trigger(reason)

    def _first_open_of_kind(self, kind: str) -> bool:
        now = time.monotonic()
        first = now - self._last_clip.get(kind, -math.inf) > TRIGGER_DEBOUNCE_S
        self._last_clip[kind] = now
        return first

    def _check_audio(self) -> None:
        """Al abrirse una ronda, comprueba que está llegando audio; si no, reconecta y avisa."""
        silent = self.buffer.silence_seconds()
        if silent <= AUDIO_STALE_S:
            log.info("Audio del directo OK")
            return
        what = "nunca ha llegado audio" if math.isinf(silent) else f"no llega audio desde hace {silent:.0f} s"
        self.notifier.info(f"¡OJO! Ronda abierta pero {what}. Reconectando con Kick…")
        if self.source is not None:
            self.source.restart(what)

    def _on_raffle_closed(self) -> None:
        self._active_until = time.monotonic() + self.cfg.trigger.listen_after_seconds
        log.info("Ronda cerrada; sigo escuchando %.0f s más por el retraso del stream",
                 self.cfg.trigger.listen_after_seconds)

    def _new_round(self) -> None:
        with self._lock:
            self._alerted.clear()  # una ronda nueva puede repetir contraseña
            self._confirmed = None
            self._round_done = False

    def _on_hotkey(self) -> None:
        self._new_round()  # la tecla fuerza a escuchar otra vez aunque ya hubiera contraseña
        self._active_until = max(self._active_until, time.monotonic() + self.cfg.trigger.hotkey_seconds)
        if self.clips:
            self.clips.capture("tecla rápida", at=self.buffer.now)  # "ahora" = lo que estás oyendo
        self.trigger("tecla rápida")

    # --- detección -----------------------------------------------------------------------

    def _on_commit(self, new: list[Segment]) -> None:
        recent = self.transcript.since(self.buffer.now - self.cfg.extract.window_seconds)
        self._report(extract(recent), "en vivo", confirmed=False)

    def _report(self, candidates: list[Candidate], reason: str, confirmed: bool) -> None:
        """Avisa de la mejor candidata si supera el umbral y no se avisó ya con esa confianza.

        Lo de en vivo es provisional (Whisper ve trozos cortos y a veces corta la contraseña); la revisión
        precisa la confirma. **Una sola contraseña confirmada por ronda**: en cuanto la hay se deja de escuchar
        hasta la próxima ronda (si no, una frase posterior como "uno más era la clave", hablando de otra cosa,
        se tomaría por una segunda contraseña).
        """
        if not self._raffle_active and self.cfg.trigger.transcribe == "raffle":
            return
        good = [c for c in candidates if c.score >= self._threshold]
        if not good:
            return
        best = good[0]
        with self._lock:
            if self._confirmed is not None:
                return
            if not confirmed and self._alerted.get(best.key, 0) >= best.score:
                return
            self._alerted[best.key] = max(best.score, self._alerted.get(best.key, 0))
            if confirmed:
                self._confirmed = best.key
                self._round_done = True
        self.notifier.alert(good, reason, provisional=not confirmed)
        if confirmed and self.joiner:
            self.joiner.submit(best)
        if confirmed:
            log.info("Contraseña confirmada; no escucho más hasta la próxima ronda (Ctrl+Alt+P para forzar)")

    def _on_join_result(self, results: list[JoinResult]) -> None:
        joined = [r for r in results if r.joined]
        summary = " · ".join(map(str, results))
        self.notifier.info(f"Auto-entrada {'OK' if joined else 'FALLÓ'}: {summary}")

    def trigger(self, reason: str) -> None:
        """Avisa y repasa con precisión el audio de justo antes del disparo (lo de después va en vivo)."""
        now = time.monotonic()
        if now - self._last_trigger < TRIGGER_DEBOUNCE_S:
            return
        self._last_trigger = now
        doing = "Escuchando la contraseña…" if self.whisper_enabled else "Grabando el clip para Discord…"
        self.notifier.info(f"{reason[:1].upper()}{reason[1:]}. {doing}")
        threading.Thread(target=self._precise, args=(self.cfg.trigger.reanalyze_seconds, f"antes de: {reason}"),
                         daemon=True).start()

    def _precise(self, seconds: float, reason: str) -> None:
        """Transcribe con más precisión (beam 5 + prompt) los últimos `seconds` y busca la contraseña.

        Va aparte de la transcripción en vivo: no se mezcla con el transcript para no contar repeticiones dobles.
        """
        if self.transcriber is None:
            return
        now = self.buffer.now
        audio, start = self.buffer.read(now - seconds, now)
        segments = self.transcriber.transcribe(audio, start, precise=True)
        self._report(extract(segments), f"revisión · {reason}", confirmed=True)

    def _review_loop(self) -> None:
        """Con ronda abierta, cada `review_every_seconds` de audio repasa con precisión el último minuto.

        En vivo Whisper ve trozos cortos y se equivoca más; con 60 s de contexto acierta mucho más.
        """
        last = self.buffer.now
        while not self.stop.wait(1):
            if not self._raffle_active:
                last = self.buffer.now
                continue
            if self.buffer.now - last >= self.cfg.trigger.review_every_seconds:
                last = self.buffer.now
                self._precise(self.cfg.trigger.review_window_seconds, "último minuto")
