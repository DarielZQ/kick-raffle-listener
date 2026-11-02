# Handoff

Notas para quien retome el proyecto.

## En una frase

Bot local que escucha un directo de Kick y, cuando la API pública de estado del sitio de sorteos abre una
ronda, manda a Discord un clip de audio de 20 s antes a 70 s después (y lo borra a los 15 min). Opcionalmente
(`transcribe = "raffle"`) transcribe con faster-whisper y saca la contraseña con reglas.

## Dónde está cada cosa

- Entrada: `src/raffle_listener/__main__.py` → `app.py` (orquestación e hilos).
- Lógica a afinar: `src/raffle_listener/extract/rules.py` (patrones, palabras de corte, pesos).
- API de la web: `src/raffle_listener/triggers/site_poller.py` (formato del JSON documentado en
  `docs/research.md` §4).
- Config: `config.example.toml` → copiar a `config.toml` (ignorado por git; ahí van el canal, las URLs del
  sitio y el webhook de Discord). `config.missing_settings` comprueba que no queden marcadores.
- Arranque: `raffle-listener.cmd` (y el lanzador global que crea `scripts/setup.ps1`).

## Estado

Ver `PROJECT_STATUS.md`.

## Convenciones

- Docs y comentarios en español; identificadores en inglés.
- Tiempos internos = segundos de audio recibidos desde el arranque (no hora del reloj).
- `extract/` sin dependencias externas para que los tests sean instantáneos.
- Cualquier frase de un sorteo que falle → añadir un caso equivalente (inventado, sin datos de terceros) a
  `tests/test_rules.py` o a `tests/fixtures/` antes de tocar las reglas.
- Nada específico de un canal o sitio en el código: va en `config.toml`.

## Límites acordados

- Avisa en local y en el canal de Discord del usuario; opcionalmente (`[autojoin]`) entra en el sorteo con
  la sesión del propio usuario, solo con contraseñas confirmadas (decisión en `docs/decisions.md`).
- `config.toml`, la sesión del navegador (`.browser/`) y cualquier audio o log quedan fuera de git.
- Todo local y gratis. Nada de audio en disco (clips en memoria).
