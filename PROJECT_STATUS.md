# Estado del proyecto

## Fase: modo clip (sin Whisper) y detección automática disponibles

| Pieza | Estado | Verificado |
|-------|--------|------------|
| Extractor por reglas | Hecho | Tests unitarios + 5 transcripciones sintéticas con los casos difíciles |
| Audio de Kick (streamlink + ffmpeg) | Hecho | Directo real; vigilante que reconecta si no llega audio en 20 s (test con stream colgado) |
| Whisper `large-v3-turbo` en GPU | Hecho | GPU de 6 GB, int8: varias veces más rápido que tiempo real |
| Transcripción solo con ronda abierta + revisión precisa | Hecho | `replay.py` con grabaciones de rondas |
| Sondeo de la API de estado del sitio (abre/cierra ronda) | Hecho | Tests con la estructura del JSON |
| Audio loopback | Hecho | **Sin probar** |
| Tecla rápida | Hecho | **Sin probar** |
| Toast / portapapeles | Hecho | Uso en directo |
| Discord (webhook) | Hecho | Tests + envío de prueba |
| Auto-entrada en el formulario del sitio | Hecho | Tests contra un widget sintético; **falta una ronda real con sesión** |
| Clip de cada ronda → Discord → borrado a los 15 min | Hecho | `clip_vod_check.py` con VODs; bot completo en modo `off` con Discord simulado |
| Clip de los Guess (mensaje "GUESS") | Hecho | Tests con la estructura del JSON |
| Aviso de ganadores de la lista (IDs de Discord) | Hecho | Tests con datos inventados y Discord simulado |
| Comando `raffle-listener` (CMD) | Hecho | Arranca desde cualquier carpeta |
| Canal, URLs y textos del sitio configurables | Hecho | Tests de `missing_settings` |

## Siguiente

1. `raffle-listener --login` (una vez, solo si se usa la auto-entrada) y luego `raffle-listener` en el
   próximo directo.
2. Si falla alguna detección, añadir un caso equivalente inventado a `tests/test_rules.py` o
   `tests/fixtures/` y ajustar las reglas.
3. Probar la tecla rápida y las notificaciones de Windows.

## Riesgos

- El clip asume que la contraseña se dice al principio de la ronda; si se dice más tarde, no saldrá en él.
- El retraso del audio de Kick (`stream_delay_seconds = 8`) es una estimación.
- La pasada en vivo da a veces provisionales erróneas; la confirmada llega ≤30 s después.
- En `replay.py` a velocidad ×3 la GPU puede ir justa ("se saltan N s"); a velocidad real no debería pasar.
- Si Kick cambia su web, el plugin de streamlink puede romperse → `source = "loopback"`.
- Si el sitio de sorteos cambia su API o su formulario, hay que ajustar `config.toml` (o el parser).
