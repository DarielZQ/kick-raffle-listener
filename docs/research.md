# Investigación

## 1. Obtener el audio del stream de Kick

| Opción | Pros | Contras |
|--------|------|---------|
| **streamlink → ffmpeg** (elegida por defecto) | Audio limpio, independiente del navegador y del volumen. streamlink trae plugin de Kick. | Kick usa Cloudflare y a veces bloquea; el plugin puede romperse cuando Kick cambia. |
| **Loopback de Windows (WASAPI)** con `soundcard` (alternativa) | Funciona siempre que el stream suene en el PC. Cero dependencia de Kick. | Captura todo lo que suena (notificaciones, música); el volumen del navegador importa. |
| API de Kick (`/api/v2/channels/<canal>` → `playback_url`) | Directo. | Protegida por Cloudflare; casi siempre devuelve 403 sin navegador. |

Comando base: `streamlink --stdout https://kick.com/<canal> worst | ffmpeg -i pipe:0 -vn -ac 1 -ar 16000 -f s16le pipe:1`.
Se usa la calidad `worst` porque solo interesa el audio.

## 2. Transcripción local (speech-to-text)

- **faster-whisper** (Whisper sobre CTranslate2): 4× más rápido que el Whisper original, con VAD integrado.
- Modelo recomendado para una GPU de 6 GB: **`large-v3-turbo`** con `compute_type="int8_float16"`
  (~2–3 GB de VRAM, muy buen español). Si va lento: `medium` o `small`.
- En Windows, la GPU necesita las DLL de cuBLAS y cuDNN 9 (CUDA 12). Se instalan con pip
  (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`) y el código añade sus carpetas `bin` al buscador de DLL.
  Si falla, cae a CPU con un modelo más pequeño.
- **Whisper no es streaming**: se transcribe una ventana deslizante (últimos ~10–25 s) cada ~3 s y solo
  se "confirman" los segmentos que ya terminaron (técnica tipo *local agreement* simplificada).
- `initial_prompt` sirve para sesgar el vocabulario ("sorteo, raffle, la contraseña es…") en el re-análisis.

Riesgo principal: **palabras raras mal transcritas** ("patata de papa" → "patata de papá"). Mitigación:
re-análisis con `beam_size=5` (revisión periódica del último minuto).

## 3. Extraer la contraseña del texto (todo local)

1. **Reglas (elegida para el MVP)**: patrones como "la contraseña/clave/palabra/código es X",
   "contraseña: X", "X es la contraseña", "pongan X". Se corta la captura en signos de puntuación o
   palabras de corte ("no", "y", "pero", "vale"…), máximo 4 palabras. Se puntúa por tipo de patrón y
   por repeticiones (los streamers suelen repetirla).
2. **Rareza de la palabra** (idea futura): con `wordfreq`, penalizar candidatas muy comunes
   ("bien", "eso") y premiar las raras.
3. **LLM local con Ollama** (idea futura): `qwen2.5:3b` o similar recibe los últimos 2 min de texto y
   responde la contraseña. Cubre frases que las reglas no ven. Ojo: comparte la VRAM con Whisper.

## 4. Detectar el sorteo en la web: API de estado público

Muchos sitios de sorteos para streamers tienen una página que consulta cada pocos segundos una API JSON
pública (sin login) con el estado de los sorteos. El bot consulta esa misma URL (`[trigger].site_url`) cada
`site_interval_seconds`. Formato que espera (`triggers/site_poller.py` y `winners.py`):

- `cajas.raffle.rounds[]` → rondas por secciones. Cada ronda: `id`, `section` (`no_subs` | `subs`),
  `status` (`open` mientras se puede entrar; `drawn`, `closed`, `cancelled`, `finished` o `ended` cuando no),
  `slots` (ganadores), `passwordRequired`, `createdAt`, `drawnAt`, `participants`, `winners`.
  `cajas.raffle.winnerEntries[]` lista también ganadores con `roundId` y `section`.
- `raffles.raffles[]` → otros sorteos: `id`, `title`, `status`, `participationOpen`, `passwordRequired`,
  `potentialWinners`, `confirmedWinners`.
- `guess.guesses[]` y `guess.guess` → los Guess, con los mismos campos.
- Cada ganador: `discordId`, `discordUsername` (el @ único), `discordGlobalName`/`displayName`, `status`,
  `prizeUsd`, `confirmedAt`.
- **La contraseña no aparece en la API**: la comprueba el servidor al enviar el formulario
  (`[autojoin].join_path`). Por eso escuchar el audio es la única vía (y la legítima).

Si un sitio usa otro formato, hay que adaptar `open_raffles` y `winners_in`; el resto del bot no cambia.

**Retraso a tener en cuenta**: la API va en tiempo real, pero el audio de Kick (HLS) llega con unos
5–15 s de retraso. Si el streamer dice la contraseña justo al abrir la ronda, llega al bot *después*
del disparo. Por eso, tras el disparo se sigue escuchando `listen_after_seconds` con umbral más bajo.

Descartado: vigilar el DOM con Playwright/extensión (más frágil y necesita el navegador abierto).

## 5. VODs de Kick para pruebas

`https://kick.com/api/v2/channels/<canal>/videos` lista los VODs del canal, incluido el directo en curso
(`is_live: true`), con `source` = `master.m3u8`. Una variante de baja calidad (p. ej. `160p30/playlist.m3u8`)
basta para sacar el audio con ffmpeg (`-ss` funciona sobre HLS). Con la hora de inicio del directo,
`createdAt` de cada ronda → minuto del VOD (`scripts/raffle_history.py --vod-start`).

## 6. Cómo se dice la contraseña en la práctica

Patrones observados al probar con grabaciones de sorteos (las transcripciones de `tests/fixtures/` son
sintéticas, inventadas, pero reproducen estos casos):

- Se dice **al principio de la ronda**, normalmente en los primeros segundos o decenas de segundos.
- Casi nunca se dice "la contraseña **es**": se dice "Contraseña, X". Whisper en vivo no pone puntuación,
  pero **corta segmentos en las pausas**, y esos cortes delimitan la contraseña igual que una coma.
- Se repite (x2–x5), lo que sube la confianza.
- Antes de decirla se habla *de* la contraseña ("¿Qué contraseña ponemos?", "la contraseña la voy a
  hacer…"): las reglas tienen listas de palabras que descartan esas frases.
- A veces se dice sin la palabra "contraseña": "sorteo de las cajas: X" (Whisper: "sortido de las cajas X").
- La pasada en vivo, sola, falla (ventanas que parten "contraseña" en "…seña", "girasol en la · mochila",
  risas "Ja, ja"): de ahí la revisión periódica con más contexto y los avisos provisionales.

## 7. "La pass es…" → Whisper escribe "la paz es"

- Es habitual decir "la **pass** es X" y Whisper lo transcribe "la **paz** es X". Las reglas aceptan
  "paz"/"pas" solo en los patrones fuertes ("la paz es X", "la paz: X"); "paz, X" o "la paz sea contigo" no
  cuentan. El prompt de la revisión precisa incluye "la pass es".
- ¿Se puede "entrenar"? Afinar Whisper (fine-tuning) exige horas de audio etiquetado y no compensa para un
  puñado de frases. Lo que funciona aquí es: (1) añadir cada fallo como caso de prueba y ajustar las reglas,
  (2) sesgar el vocabulario de Whisper con el prompt. Alternativa futura, también gratis y local: un LLM
  pequeño con Ollama que lea el último minuto de texto y responda la contraseña.

## 8. Otras ideas

- **Chat de Kick** como señal extra: si muchos escriben la misma palabra rara justo después del sorteo
  (aunque el streamer pida que no), es otra pista. Kick usa Pusher (websocket) para el chat.
- **Tecla rápida** como disparador manual: siempre disponible, aunque la web no se pueda vigilar.
