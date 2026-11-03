"""Auto-entrada contra un widget sintético servido en un dominio falso: nunca sale a internet."""

import json
from pathlib import Path

import pytest

from raffle_listener.autojoin import attempts_for, join_on_page, logged_in
from raffle_listener.config import AutoJoinConfig
from raffle_listener.extract import Candidate

WIDGET = (Path(__file__).parent / "fixtures" / "widget_sorteo.html").read_text(encoding="utf-8")
FAKE_URL = "https://sorteos.test/directo"
CFG = AutoJoinConfig(page_url=FAKE_URL, widget_text="Sorteo de ejemplo", join_path="/api/sorteo/join")


def cand(text, joined=False):
    return Candidate(text, text.lower(), 0.9, "contraseña_x", 0.0, 1, "…", joined)


def test_attempts_order():
    assert attempts_for(cand("girasol en la mochila", joined=True), 3) == [
        "girasolenlamochila", "girasol en la mochila", "GirasolEnLaMochila"]
    assert attempts_for(cand("Dragón"), 3) == ["Dragón", "dragon"]


@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api", reason="Playwright no está instalado (extra autojoin)")
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome", headless=True)
        except Exception as exc:  # sin Chrome instalado
            pytest.skip(f"No se pudo abrir Chrome: {exc}")
        yield b
        b.close()


@pytest.fixture
def site(browser):
    """Página con el widget sintético; /api/sorteo/join solo acepta "llave" y registra lo que recibe."""
    page = browser.new_page()
    posts = []

    def handle(route):
        if route.request.url.split("?")[0].endswith("/directo"):
            return route.fulfill(status=200, content_type="text/html", body=WIDGET)
        if CFG.join_path in route.request.url:
            data = json.loads(route.request.post_data)
            posts.append((data["section"], data["password"]))
            ok = data["password"] == "llave"
            return route.fulfill(status=200 if ok else 400, content_type="application/json",
                                 body=json.dumps({"ok": ok} if ok else {"ok": False, "message": "Contraseña incorrecta"}))
        return route.abort()

    page.route("**/*", handle)
    yield page, posts
    page.close()


def test_joins_open_section_and_skips_closed_one(site):
    page, posts = site
    page.goto(FAKE_URL + "?open=no_subs")
    results = join_on_page(page, ["llave"], CFG)
    assert [(r.section, r.joined) for r in results] == [("No Subs", True), ("Subs", False)]
    assert "sin formulario" in results[1].detail
    assert posts == [("no_subs", "llave")]


def test_tries_variants_until_accepted(site):
    page, posts = site
    page.goto(FAKE_URL + "?open=no_subs,subs")
    results = join_on_page(page, ["Llave", "llave"], CFG)
    assert all(r.joined for r in results)
    assert posts == [("no_subs", "Llave"), ("no_subs", "llave"), ("subs", "Llave"), ("subs", "llave")]


def test_reports_rejection(site):
    page, posts = site
    page.goto(FAKE_URL + "?open=no_subs")
    results = join_on_page(page, ["uno más"], AutoJoinConfig(
        widget_text=CFG.widget_text, join_path=CFG.join_path, sections=["No Subs"]))
    assert not results[0].joined
    assert "Contraseña incorrecta" in results[0].detail


def test_detects_missing_session(site):
    page, _ = site
    page.goto(FAKE_URL + "?logged=0")
    assert not logged_in(page, CFG.login_text)
    page.goto(FAKE_URL)
    assert logged_in(page, CFG.login_text)
