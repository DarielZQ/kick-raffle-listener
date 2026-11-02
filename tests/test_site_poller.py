from raffle_listener.triggers.site_poller import SitePoller, open_raffles


def state(rounds, raffles=()):
    """Forma reducida del JSON de estado público que espera el bot (ver docs/research.md §4)."""
    return {"ok": True, "cajas": {"ok": True, "raffle": {"id": "x", "status": "active", "rounds": list(rounds)}},
            "raffles": {"ok": True, "raffles": list(raffles)}}


def rnd(id_, section, status):
    return {"id": id_, "section": section, "slots": 4, "status": status, "participants": [],
            "createdAt": "2026-01-01T21:45:30.000Z", "drawnAt": None, "winners": [], "passwordRequired": True}


def test_only_open_rounds_are_reported():
    events = open_raffles(state([rnd("a", "no_subs", "drawn"), rnd("b", "no_subs", "open"), rnd("c", "subs", "open")]))
    assert [(e.id, e.section, e.password_required) for e in events] == [("b", "no_subs", True), ("c", "subs", True)]


def test_closed_state_and_missing_sections():
    assert open_raffles(state([rnd("a", "subs", "drawn")])) == []
    assert open_raffles({"ok": True, "cajas": {"ok": True, "raffle": None}}) == []


def test_generic_raffles_are_reported():
    events = open_raffles(state([], [{"id": 7, "title": "Sorteo", "status": "active", "participationOpen": True,
                                      "passwordRequired": True}]))
    assert events[0].kind == "raffle" and events[0].id == "7"


def test_open_guess_is_reported():
    # Igual que la web: abierta si no está "closed"/"cancelled" y participationOpen es verdadero.
    st = state([])
    st["guess"] = {"ok": True, "guess": {"id": "g1", "title": "¿Cuánto paga?", "status": "active",
                                         "participationOpen": True, "passwordRequired": True},
                   "guesses": [{"id": "g1", "title": "¿Cuánto paga?", "status": "active",
                                "participationOpen": True, "passwordRequired": True},
                               {"id": "g0", "title": "Viejo", "status": "closed",
                                "participationOpen": False, "passwordRequired": True}]}
    events = open_raffles(st)
    assert [(e.kind, e.id, e.section) for e in events] == [("guess", "g1", "¿Cuánto paga?")]


def test_locked_guess_is_not_open():
    st = state([])
    st["guess"] = {"ok": True, "guess": None, "guesses": [
        {"id": "g2", "title": "Bloqueado", "status": "active", "participationOpen": False, "passwordRequired": True}]}
    assert open_raffles(st) == []


def test_ignores_closed_participation_and_no_password():
    # Un sorteo genérico puede seguir "active" con la participación ya cerrada y sin contraseña.
    closed = {"id": 1, "title": "Raffle 5 × $5", "status": "active", "participationOpen": False, "passwordRequired": False}
    no_pw = {"id": 2, "title": "Raffle", "status": "active", "participationOpen": True, "passwordRequired": False}
    cajas_no_pw = dict(rnd("c", "subs", "open"), passwordRequired=False)
    assert open_raffles(state([cajas_no_pw], [closed, no_pw])) == []


def test_poller_reports_each_round_once_and_the_close():
    fired = []
    states = iter([state([rnd("a", "no_subs", "drawn")]),
                   state([rnd("b", "no_subs", "open"), rnd("c", "subs", "open")]),
                   state([rnd("b", "no_subs", "open"), rnd("c", "subs", "open")]),
                   state([rnd("b", "no_subs", "drawn"), rnd("c", "subs", "drawn")])])

    class Stop:
        n = 0

        def is_set(self):
            return self.n >= 4

        def wait(self, _):
            self.n += 1

    poller = SitePoller("http://x", 0, lambda ev: fired.append(ev.id), lambda: fired.append("closed"))
    poller.fetch = lambda: next(states)
    poller.run(Stop())
    assert fired == ["b", "c", "closed"]
