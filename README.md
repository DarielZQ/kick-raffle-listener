# Raffle Listener

Escucha un directo de **Kick**, transcribe en local lo que se dice y detecta la **contraseña de los sorteos**
que el streamer dice en voz alta ("la contraseña es *patata de papa*…"). Cuando la encuentra, avisa con una
notificación y un sonido, la **copia al portapapeles** y, si quieres, la **envía a un canal de Discord**
(webhook). Opcionalmente puede **meterla él mismo** en el formulario del sitio de sorteos con tu sesión.

Además puede vigilar la API pública de estado del sitio de sorteos para saber cuándo se abre una ronda, mandar
a Discord un **clip de audio** de cada apertura (y borrarlo pasados unos minutos) y avisar cuando gana alguien
de una lista de usuarios de Discord.

Todo corre en tu PC y es gratis (Whisper en la GPU con faster-whisper). Nada de audio se guarda en disco.

> **Aviso.** Úsalo solo de forma compatible con las reglas del sitio de sorteos, de Kick y de Discord, y con
> las del propio streamer. Muchos sorteos prohíben participar de forma automatizada: la auto-entrada viene
> desactivada y activarla es decisión y responsabilidad de quien lo usa. El proyecto no está afiliado a
> ningún streamer, sitio ni plataforma.

## Instalación

Requisitos: Windows, Python 3.11+, ffmpeg en el PATH y, opcionalmente, una GPU NVIDIA.

```bash
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
```

Esto crea `.venv`, instala dependencias (incluidas las DLL de CUDA), copia `config.example.toml` a
`config.toml` y crea el comando global `raffle-listener`. La primera ejecución descarga el modelo de Whisper
(~1,6 GB).

Sin el script, con cualquier gestor de entornos:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[cuda,loopback,toast,autojoin,dev]"
```

## Configuración para tu canal y tu sitio

Copia `config.example.toml` a `config.toml` (ignorado por git) y rellena los marcadores. El bot no arranca
mientras quede alguno: dice exactamente qué valor falta.

| Clave | Qué poner |
|-------|-----------|
| `[stream] channel` | Nombre del canal de Kick (lo que va tras `https://kick.com/`). |
| `[trigger] site_url` | URL de la API JSON con el estado público de los sorteos (la que consulta la propia página del sitio; formato esperado en [docs/research.md](docs/research.md) §4). `""` para no vigilar el sitio: entonces solo funciona la tecla rápida o `transcribe = "always"`. |
| `[output] discord_webhook` | URL del webhook de Discord. **Es secreta**: solo en `config.toml`. |
| `[autojoin] page_url`, `widget_text`, `join_path` | Solo si activas la auto-entrada: página con el formulario, texto visible que identifica el bloque del sorteo y ruta de la petición `POST` que envía la contraseña. Los textos del campo y los botones (`password_placeholder`, `submit_text`, `login_text`) también se ajustan aquí. |
| `[winners] usernames` | IDs numéricos (o @) de Discord de las personas a vigilar. |

Los valores de ejemplo (`<canal>`, `https://sitio.example/…`) son marcadores y se rechazan al arrancar.

## Uso

Desde cualquier CMD (tras `setup`):

```bash
raffle-listener
```

(`raffle-listener.cmd` está en la raíz del proyecto; `setup` deja un lanzador en
`%LOCALAPPDATA%\Microsoft\WindowsApps`, que ya está en el PATH. Para quitar el comando global, borra
`%LOCALAPPDATA%\Microsoft\WindowsApps\raffle-listener.cmd`.) También vale
`.venv\Scripts\python -m raffle_listener --config config.toml`. Ctrl+C para pararlo.

- Puedes arrancarlo **horas antes del directo**: avisa una vez de que aún no ha empezado, lo comprueba cada
  30 s en silencio y se conecta solo cuando empieza.
- `raffle-listener -v` muestra también la transcripción en vivo (útil para ver si entiende bien).
- **Ctrl+Alt+P** activa la escucha 5 min aunque la web no haya abierto ronda (o ya hubiera contraseña).
- **Una contraseña por ronda**: en cuanto la confirma, deja de escuchar hasta la próxima ronda.
- Si el audio de Kick se queda colgado, se reconecta solo a los 20 s; y si al abrirse una ronda no llega
  audio, avisa con "¡OJO! Ronda abierta pero no llega audio…" y reconecta.
- No guarda nada en disco: el audio solo vive en memoria (los últimos 5 min). Lo único que ocupa
  espacio es el modelo de Whisper (en la caché de Hugging Face del usuario).

### Clip para Discord

`[clip]` en `config.toml`. Al abrirse una ronda, el clip (20 s antes → 70 s después) se genera y se comprime a
MP3 **en memoria** (unos 530 KB), se sube al mismo webhook y el bot borra el mensaje a los
`delete_after_minutes`. Si cierras el bot antes, borra al salir los clips pendientes. **Nunca se escribe en el
disco.** En el mismo mensaje va también una copia **x2** (el mismo audio al doble de velocidad, con la misma
voz): `speed_copies = [2.0]`, o `[]` para no mandarla. `Ctrl+Alt+P` manda un clip de lo que estás oyendo.
Para probar el webhook con un clip: `raffle-listener --test-clip`.

Con `[trigger] transcribe = "off"` no se carga Whisper (arranca en segundos y no usa la gráfica); la
detección automática de la contraseña y la auto-entrada quedan desactivadas. Con `"raffle"` vuelven.

### Guess

Igual que las rondas: cuando la web abre un **Guess** con contraseña, se manda su clip con el mensaje
`message_guess`. Si un Guess y una ronda se abren a la vez, cada uno tiene su clip.

### Aviso de ganadores

En `[winners] usernames` pon el **ID numérico de Discord** de cada persona a vigilar (Discord → Ajustes →
Avanzado → Modo desarrollador; clic derecho en la persona → Copiar ID) y, opcionalmente, su @ único. Algunas
listas de ganadores solo traen el ID, así que el ID es lo más fiable. Cuando una persona de la lista sale
**confirmada** como ganadora, el bot escribe en el mismo canal mencionándola, p. ej.:

> @UsuarioEjemplo1 ¡has ganado! · Dónde: SORTEO DE EJEMPLO · Premio: 10 $ · 15/01/2026 a las 11:33

Los ganadores que ya estaban en la web al arrancar el bot no se anuncian. En la consola sale, sin nombres,
"Ganadores nuevos en …: N (con @ de Discord: M)".

### Discord

En `config.toml`, sección `[output]`:

```toml
discord_webhook = "https://discord.com/api/webhooks/<id>/<token>"   # secreto: solo en config.toml
discord_message = "Contraseña del sorteo: "
discord_provisional = false   # solo se envía la contraseña confirmada por la revisión precisa
```

Se envía un solo mensaje por ronda: la contraseña confirmada. Para comprobar el webhook:
`raffle-listener --test-discord`.

### Auto-entrada en el sorteo (opcional)

Con `[autojoin] enabled = true`, al confirmarse la contraseña el bot abre/recarga `page_url` en **su propio
Chrome**, busca el bloque que contiene `widget_text` y, en cada pestaña de `sections` donde aparezca el
formulario, escribe la contraseña y pulsa el botón que empieza por `submit_text`. Si la web la rechaza, prueba
sus variantes (sin tildes, etc.; máx. `max_attempts`). El resultado sale en consola y en una notificación.

Una sola vez, para que el Chrome del bot tenga tu sesión:

```bash
raffle-listener --login
```

Inicia sesión en la ventana que se abre y ciérrala. La sesión queda en `.browser/` (ignorado por git).
Si caduca, el bot avisa ("NO hay sesión") y basta con repetir `--login`.

## Herramientas

| Script | Para qué |
|--------|----------|
| `scripts/extract_text.py "texto"` | Probar el extractor con una frase. |
| `scripts/transcribe_file.py <vod/archivo> --start 1:11:30 --duration 240` | Transcribir un tramo de un VOD o un archivo y ver qué contraseñas detecta. |
| `scripts/raffle_history.py --vod-start <inicio UTC>` | Ver las rondas actuales del sitio y su minuto en el VOD. |
| `scripts/clip_vod_check.py "<m3u8>,<apertura>,<contraseña>"` | Comprobar con VODs qué entra en el clip de cada ronda. |
| `scripts/replay.py clip.wav --open-at 180 --speed 4` | Prueba completa: reproduce un audio como si fuera el directo. |

## Tests

```bash
.venv/Scripts/python -m pytest -q
```

Las transcripciones de `tests/fixtures/` y el widget HTML de las pruebas de auto-entrada son **sintéticos**
(inventados); las pruebas de auto-entrada usan un dominio falso y no salen a internet (se saltan si no hay
Playwright o Chrome).

## Documentación

- [docs/requirements.md](docs/requirements.md): qué tiene que hacer y preguntas abiertas
- [docs/research.md](docs/research.md): opciones investigadas (audio, transcripción, API de la web)
- [docs/architecture.md](docs/architecture.md): cómo encajan las piezas
- [docs/decisions.md](docs/decisions.md): decisiones y por qué
- [PROJECT_STATUS.md](PROJECT_STATUS.md): estado actual · [HANDOFF.md](HANDOFF.md): para retomar el trabajo
