"""Mete la contraseña en el formulario del sorteo de la web (`[autojoin].page_url`), con un Chrome y TU sesión.

El bot abre su propio Chrome (perfil aparte en `[autojoin].profile_dir`) donde has iniciado sesión una vez
con `raffle-listener --login`. Al confirmarse una contraseña: recarga la página, busca el bloque del sorteo
(`widget_text`) y, en cada pestaña (`sections`), si aparece el campo `password_placeholder`, escribe la
contraseña y pulsa el botón que empieza por `submit_text`. La web responde en `POST <join_path>`; si rechaza
la contraseña, prueba las variantes (sin tildes, etc.). Todos esos textos y rutas se configuran en
`config.toml`, porque dependen del sitio.

Playwright (API síncrona) solo se puede usar desde el hilo que lo creó: todo pasa en `AutoJoiner.run`,
y el resto de la app le manda trabajo por una cola.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
from dataclasses import dataclass
from typing import Callable

from .config import AutoJoinConfig
from .extract import Candidate, normalize, variants

log = logging.getLogger(__name__)

FORM_TIMEOUT_MS = 4_000
RESPONSE_TIMEOUT_MS = 10_000


@dataclass
class JoinResult:
    section: str
    joined: bool
    detail: str

    def __str__(self) -> str:
        return f"{self.section}: {self.detail}"


def attempts_for(cand: Candidate, max_attempts: int) -> list[str]:
    """Qué escribir y en qué orden: lo que se pega normalmente, luego sus variantes."""
    words = [cand.typed, *variants(cand.text, cand.joined), normalize(cand.text)]
    return list(dict.fromkeys(w for w in words if w))[:max_attempts]


def _section_tab(name: str) -> re.Pattern[str]:
    # Los botones son "No Subs •" / "Subs •"; "^\s*Subs" no casa con "No Subs".
    return re.compile(rf"^\s*{re.escape(name)}\b")


def _response_detail(resp) -> tuple[bool, str]:
    try:
        body = resp.json()
    except Exception:
        body = None
    ok = resp.ok and not (isinstance(body, dict) and body.get("ok") is False)
    msg = ""
    if isinstance(body, dict):
        msg = str(body.get("message") or body.get("error") or body.get("reason") or "")
    return ok, msg or f"HTTP {resp.status}"


def _starts_with(text: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(text.strip())}", re.I)


def logged_in(page, login_text: str) -> bool:
    """Sin sesión, la web muestra un botón de inicio de sesión (`login_text`) en la cabecera."""
    return page.get_by_role("button", name=_starts_with(login_text)).count() == 0


def join_on_page(page, words: list[str], cfg: AutoJoinConfig) -> list[JoinResult]:
    """Intenta entrar en cada sección del widget con `words` (en orden). No recarga la página."""
    widget = page.locator("section").filter(has_text=cfg.widget_text).first
    widget.wait_for(state="visible", timeout=10_000)
    results: list[JoinResult] = []
    for name in cfg.sections:
        tab = widget.get_by_role("button", name=_section_tab(name)).first
        if tab.count() == 0:
            results.append(JoinResult(name, False, "no existe esa pestaña"))
            continue
        tab.click()
        field = widget.get_by_placeholder(cfg.password_placeholder)
        try:
            field.wait_for(state="visible", timeout=FORM_TIMEOUT_MS)
        except Exception:
            results.append(JoinResult(name, False, "sin formulario (no hay ronda, ya estás dentro o no cumples requisitos)"))
            continue
        submit = widget.get_by_role("button", name=_starts_with(cfg.submit_text))
        result = JoinResult(name, False, "sin intentos")
        for word in words:
            field.fill(word)
            try:
                with page.expect_response(lambda r: cfg.join_path in r.url and r.request.method == "POST",
                                          timeout=RESPONSE_TIMEOUT_MS) as info:
                    submit.click()
            except Exception as exc:
                result = JoinResult(name, False, f"«{word}»: la web no respondió ({exc.__class__.__name__})")
                break
            ok, msg = _response_detail(info.value)
            if ok:
                result = JoinResult(name, True, f"DENTRO con «{word}»")
                break
            result = JoinResult(name, False, f"«{word}» rechazada: {msg}")
            log.info("%s", result)
        results.append(result)
    return results


class AutoJoiner:
    def __init__(self, cfg: AutoJoinConfig, page_url: str, on_result: Callable[[list[JoinResult]], None]) -> None:
        self.cfg = cfg
        self.page_url = page_url
        self.on_result = on_result
        self._jobs: queue.Queue[list[str]] = queue.Queue()

    def submit(self, cand: Candidate) -> None:
        self._jobs.put(attempts_for(cand, self.cfg.max_attempts))

    def _launch(self, p, headless: bool):
        args = ["--start-minimized"] if self.cfg.start_minimized and not headless else []
        return p.chromium.launch_persistent_context(self.cfg.profile_dir, channel=self.cfg.browser_channel,
                                                    headless=headless, args=args, no_viewport=True)

    def run(self, stop: threading.Event) -> None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            ctx = self._launch(p, self.cfg.headless)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(self.page_url, wait_until="domcontentloaded")
            page.wait_for_timeout(3_000)
            if logged_in(page, self.cfg.login_text):
                log.info("Auto-entrada lista: sesión iniciada en %s", self.page_url)
            else:
                log.warning("Auto-entrada: NO hay sesión en el Chrome del bot. Cierra el bot y ejecuta: raffle-listener --login")
            while not stop.is_set():
                try:
                    words = self._jobs.get(timeout=1)
                except queue.Empty:
                    continue
                try:
                    page.reload(wait_until="domcontentloaded")
                    if not logged_in(page, self.cfg.login_text):
                        self.on_result([JoinResult("-", False, "sin sesión: ejecuta raffle-listener --login")])
                        continue
                    self.on_result(join_on_page(page, words, self.cfg))
                except Exception as exc:
                    log.exception("Falló la auto-entrada")
                    self.on_result([JoinResult("-", False, f"error: {exc}")])
            ctx.close()

    def login(self) -> None:
        """Abre el Chrome del bot para que inicies sesión; la sesión queda guardada en el perfil."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            ctx = self._launch(p, headless=False)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(self.page_url)
            print("Inicia sesión en la ventana de Chrome que se ha abierto y CIÉRRALA cuando termines.", flush=True)
            page.wait_for_event("close", timeout=0)
            ctx.close()
        print("Sesión guardada. Ya puedes arrancar el bot con: raffle-listener", flush=True)
