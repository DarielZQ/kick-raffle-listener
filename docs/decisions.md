# Decisiones

Formato: decisión · por qué · alternativas descartadas. En orden aproximado de cuándo se tomaron.

## Avisar y copiar por defecto (la auto-entrada es opcional, ver más abajo)

- **Decisión**: el bot avisa y copia la contraseña al portapapeles; el usuario la pega.
- **Por qué**: enviar automáticamente puede ir contra las reglas del sorteo (riesgo de ban/descalificación)
  y una transcripción errónea enviaría basura. Con el humano en medio se puede corregir.

## Todo local y gratis

- **Decisión**: faster-whisper en la GPU + extractor por reglas.
- **Por qué**: sin costes ni dependencias de terceros; una GPU de 6 GB aguanta `large-v3-turbo` en int8.
- **Descartado**: servicios de transcripción de pago, un LLM en la nube para interpretar. Se puede añadir un
  LLM local (Ollama) más adelante detrás de la misma interfaz que `extract.rules`.

## Audio por streamlink, loopback como plan B

- **Por qué**: streamlink da audio limpio sin depender del volumen del PC; el loopback cubre el caso en
  que Kick/Cloudflare bloquee a streamlink.

## Buffer de audio y texto en memoria

- **Por qué**: la contraseña puede decirse antes de que aparezca el sorteo. Con 4–5 min guardados se puede
  re-analizar hacia atrás en el momento del disparo.

## Disparador: sondear la API pública de estado del sitio (+ tecla rápida)

- **Decisión**: consultar `[trigger].site_url` cada 3 s y disparar cuando aparece una ronda con `status`
  distinto de `drawn/closed/cancelled`. La tecla rápida queda como respaldo.
- **Por qué**: es la misma fuente que usa la página del sitio; no necesita navegador, login ni selectores CSS.
- **Descartado**: Playwright conectado al Chrome por CDP vigilando el DOM.
- **Debounce**: `no_subs` y `subs` se abren a la vez → un solo re-análisis cada 15 s.

## Canal, URLs y textos del sitio en la configuración

- **Decisión**: el código no lleva ningún canal, dominio ni texto de un sitio concreto. `[stream].channel`,
  `[trigger].site_url` y `[autojoin].page_url/widget_text/join_path` no tienen valor por defecto, y
  `config.missing_settings` hace que el arranque falle con un mensaje claro si faltan o siguen siendo los
  marcadores de `config.example.toml`.
- **Por qué**: el bot sirve para cualquier canal o sitio con la misma forma de API, y el repositorio no
  depende de terceros.

## Transcribir solo con ronda abierta

- **Decisión**: `transcribe = "raffle"` por defecto. El audio se graba siempre en memoria; Whisper solo
  trabaja desde que se abre la ronda hasta 30 s después de cerrarse.
- **Por qué**: la contraseña se dice con la ronda abierta; transcribir toda la ronda la cubre y ahorra GPU el
  resto del directo.
- **Alternativa conservada**: `transcribe = "always"` por si se dice antes de abrir.

## Patrón "Contraseña, X" y cortes de segmento como puntuación

- **Por qué**: es la forma más habitual de decirla. Los cortes de Whisper hacen de comas.
- **Riesgo**: "contraseña" va seguido a menudo de otras cosas → patrón débil (0.7) con listas de descarte,
  validado con las transcripciones de `tests/fixtures/` sin falsos positivos.

## Discord por webhook, solo contraseñas confirmadas

- **Decisión**: `[output].discord_webhook` envía `discord_message` + la contraseña cuando la revisión precisa
  la confirma. Las provisionales no se envían (`discord_provisional = false`).
- **Por qué**: lo provisional falla a veces ("Seña", "Ja", "Pero la voy"); en un canal no se puede
  "despegar" un mensaje erróneo como se sobrescribe el portapapeles.
- La URL del webhook es secreta: vive solo en `config.toml` (ignorado por git), nunca en el ejemplo.

## Auto-entrada en el formulario del sitio (opcional, solo para la cuenta del usuario)

- **Decisión**: `[autojoin]` abre un Chrome propio (perfil persistente en `.browser/`, sesión iniciada por el
  usuario con `raffle-listener --login`) y, con la contraseña **confirmada**, rellena el campo
  `password_placeholder` y pulsa el botón `submit_text` en cada pestaña con formulario. Lee la respuesta de
  `POST <join_path>` para saber si entró.
- **Por qué con el navegador y no llamando a la API**: usa la sesión real del usuario sin que el bot maneje
  tokens, y hace exactamente lo que haría él a mano. Si cambia la API, el formulario suele seguir igual.
- **Riesgos**: si la contraseña confirmada fuese errónea se envían hasta `max_attempts` intentos; el sitio
  puede considerar la entrada automática contra sus normas (decisión y responsabilidad del usuario).
- **Pruebas**: `tests/test_autojoin.py` contra un widget sintético en un dominio falso.

## Una contraseña confirmada por ronda y nada en disco

- **Problema**: tras confirmar la contraseña, la revisión periódica seguía activa y podía aceptar otra frase
  posterior (p. ej. "uno más era la clave", hablando de otra cosa).
- **Decisión**: al confirmar la primera contraseña se avisa y se deja de transcribir hasta la próxima ronda.
  La revisión periódica se mantiene **hasta** esa confirmación.
- **Reglas**: "X es la clave" ya no cuenta ("clave" es muy figurativo), "era" tampoco, y "clave, X" no cuenta si
  va precedido de "es/era/fue la".
- **Audio**: no se guardan `.wav`; el audio solo vive en el buffer de memoria.

## Comando `raffle-listener`

- `raffle-listener.cmd` en la raíz + lanzador en `%LOCALAPPDATA%\Microsoft\WindowsApps` (ya está en el PATH
  del usuario, no hace falta tocar variables de entorno). `scripts/setup.ps1` lo crea.

## Sorteos genéricos: mirar `participationOpen`

- Un sorteo puede seguir en `status: "active"` con la participación cerrada y sin contraseña. Una ronda solo
  activa la escucha si `participationOpen` no es `false` y `passwordRequired` es verdadero.

## "paz" = "pass", adverbios fuera, desempate por repeticiones, 60 s antes de abrir

- **Problema**: "la pass es X" se transcribe "la paz es X"; y frases como "puede decir la contraseña ·
  Siempre · pero…" daban "siempre" como candidata.
- **Decisiones**: "paz"/"pas" como sustantivo solo en patrones fuertes; adverbios ("siempre", "nunca",
  "ahora"…) descartan una candidata; en empate gana la más repetida; prompt de la revisión con "la pass es";
  `reanalyze_seconds = 60` para cubrir 30 s antes de abrir aunque el audio de Kick vaya ~10 s tarde.

## Vigilante de audio y "sorteo de las cajas: X"

- **Problema**: streamlink puede quedarse colgado con las conexiones abiertas y sin datos; la lectura de ffmpeg
  se bloquea para siempre y el bot no lo nota. Además, a veces la contraseña se dice como "Sorteo de las
  cajas: X", sin "contraseña" ni "pass".
- **Decisiones**: hilo vigilante en `KickSource` que mata y relanza streamlink/ffmpeg si no llega audio en 20 s
  (más `--stream-timeout 20` en streamlink); al abrirse una ronda se comprueba que llega audio y, si no, se
  reconecta y se avisa con una notificación; nuevo patrón débil "sorteo/sortido de (las) cajas X".

## Modo clip: audio de la ronda a Discord en vez de interpretar con Whisper

- **Decisión**: al abrirse una ronda, clip de 20 s antes a 70 s después → Discord (mismo webhook) → se borra
  el mensaje a los 15 min. La gente del canal de Discord escucha la contraseña. `transcribe = "off"`: sin
  Whisper ni auto-entrada (siguen disponibles con `"raffle"`).
- **Por qué**: Whisper falla con palabras raras, mayúsculas y tildes; un humano no.
- **Sin disco**: el clip se corta del buffer de memoria, se comprime con ffmpeg por tuberías y se sube desde
  memoria. Al cerrar el bot se borran los clips pendientes de Discord.
- **Validación**: `scripts/clip_vod_check.py` con VODs comprueba que la contraseña cae dentro del clip.
- **Retraso del directo**: `stream_delay_seconds = 8` (estimado; el audio de Kick llega tarde respecto a la web).

## Guess con clip y aviso de ganadores de una lista

- **Guess**: se da por abierto si `status` no es "closed"/"cancelled" y `participationOpen` es verdadero.
  Misma regla que los sorteos → mismo clip, con mensaje "GUESS · …". Clip por tipo: una ronda y un Guess a la
  vez tienen un clip cada uno.
- **Ganadores**: se compara por @ de Discord o por ID, nunca por nombre visible (puede repetirse o cambiar); se
  menciona con `<@id>` + `allowed_mentions` para que llegue la notificación. Solo ganadores confirmados (los
  generados pueden re-sortearse) y nunca los que ya estaban al arrancar.
- **Rondas por secciones**: sus ganadores pueden traer solo `discordId` y un nombre visible, sin el @. Por eso
  la lista admite IDs; el bot también aprende ID → @ de otras listas del mismo JSON.

## Copia x2 del clip en el mismo mensaje

- **Por qué no un botón**: el reproductor de Discord no tiene velocidad para archivos normales (solo las notas de
  voz, que un webhook no puede enviar) y los botones de mensaje exigen un bot de Discord con interacciones.
- **Decisión**: adjuntar al mismo mensaje una segunda copia acelerada (`atempo=2`, sin cambiar el tono), hecha en
  memoria como el clip normal y borrada con el mensaje. 90 s → 45 s, la mitad de peso.
