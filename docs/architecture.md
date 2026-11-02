# Arquitectura

## Flujo

```
                ┌──────────────────────┐
 Kick (HLS) ──► │ audio.sources        │  streamlink→ffmpeg  o  loopback WASAPI
 o altavoces    └─────────┬────────────┘
                          │ PCM 16 kHz mono (float32)
                          ▼
                ┌──────────────────────┐
                │ audio.buffer         │  anillo con los últimos N s de audio
                └─────────┬────────────┘
                          │ cada ~3 s, ventana deslizante
                          ▼
                ┌──────────────────────┐
                │ stt.live             │  faster-whisper, confirma segmentos terminados
                └─────────┬────────────┘
                          ▼
                ┌──────────────────────┐        ┌──────────────────────┐
                │ transcript           │ ─────► │ extract.rules        │  candidatas + puntuación
                │ (últimos N s texto)  │        └─────────┬────────────┘
                └──────────────────────┘                  ▼
                                                ┌──────────────────────┐
 tecla rápida ─┐                                │ notify               │  toast, sonido,
 API del sitio┴──► app.trigger() ──────────►   │                      │  portapapeles, Discord
               (re-análisis preciso de los      └──────────────────────┘
                últimos minutos + umbral más bajo)
```

## Cuándo trabaja Whisper (`[trigger].transcribe`)

- **`raffle` (por defecto)**: el audio entra siempre al buffer, pero Whisper solo transcribe mientras hay
  una ronda abierta en el sitio de sorteos, más `listen_after_seconds` tras cerrarse (el audio de Kick va con
  retraso), o durante `hotkey_seconds` tras pulsar la tecla rápida. Al abrirse, además se transcribe con
  más precisión (`beam_size=5` + prompt) el audio de los `reanalyze_seconds` anteriores.
- **`always`**: transcribe todo el directo; fuera de ronda exige `min_score` (más alto) para avisar.

Con ronda abierta hay **dos pasadas**:

1. **En vivo** (`stt/live.py`): ventanas cortas cada 3 s → aviso rápido pero **provisional**. Las ventanas
   se cortan siempre al inicio de un segmento (tras una pausa) para no partir palabras.
2. **Revisión** (`App._review_loop`): cada `review_every_seconds` se re-transcribe el último
   `review_window_seconds` con `beam_size=5` + prompt. Es la que más acierta; su resultado
   es la contraseña **confirmada**. **Una por ronda**: al confirmarla se avisa (Discord incluido) y se deja de
   transcribir hasta la próxima ronda (o hasta pulsar Ctrl+Alt+P).

Se avisa a partir de `min_score_raffle`. Cada vez que llega texto nuevo se analizan los
últimos `extract.window_seconds`, así las repeticiones suben la confianza.

## Módulos (`src/raffle_listener/`)

| Módulo | Responsabilidad |
|--------|-----------------|
| `config.py` | Carga `config.toml` en dataclasses con valores por defecto y comprueba que no falten el canal ni las URLs del sitio. |
| `audio/buffer.py` | Buffer circular thread-safe; tiempos en segundos de audio recibido. |
| `audio/sources.py` | `KickSource` (streamlink+ffmpeg, reconecta) y `LoopbackSource`. |
| `stt/transcriber.py` | Envoltorio de faster-whisper (carga GPU/CPU, DLL de CUDA, lock). |
| `stt/live.py` | Bucle de ventana deslizante que confirma segmentos sin duplicarlos. |
| `transcript.py` | `Segment` y almacén de segmentos recientes. |
| `extract/rules.py` | Extractor por reglas, sin dependencias externas (fácil de testear). |
| `triggers/` | `hotkey.py` (pynput) y `site_poller.py` (consulta la API de estado del sitio y avisa de rondas nuevas). |
| `autojoin.py` | Chrome propio con Playwright: rellena y envía el formulario del sorteo (textos y ruta configurables). |
| `clips.py` | Clip de la ronda desde el buffer → MP3 en memoria → webhook de Discord → borrado programado. |
| `winners.py` | Ganadores confirmados del JSON público → si su @ está en la lista, mensaje con mención en Discord. |
| `notify.py` | Consola, portapapeles, toast de Windows, pitido y Discord (nada en disco). |
| `app.py` | Orquesta hilos y conecta todo. |

## Hilos

- Fuente de audio → escribe en el buffer.
- Transcripción en vivo → lee buffer, escribe transcript, llama a `App._on_commit`.
- Disparadores (tecla, sondeo de la web) → llaman a `App.trigger`, que lanza el re-análisis en otro hilo.
- El modelo Whisper está protegido por un lock (el bucle en vivo y el re-análisis lo comparten).

## Base de tiempo

Todos los tiempos (`Segment.start/end`, `buffer.now`) son **segundos de audio recibidos desde el arranque**,
no la hora del reloj. Así audio y texto siempre cuadran aunque haya cortes o retrasos.
