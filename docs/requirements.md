# Requisitos

## Problema

En un stream de **Kick**, en algún momento aparece un **sorteo** en **otra web** (abierta en otra
pestaña del navegador). Para entrar hace falta una **contraseña** que el streamer **dice en voz alta**,
sin una frase fija. Ejemplo:

> "La contraseña es *patata de papa*, no la digan en el stream."

La contraseña suele ser una palabra o frase corta y llamativa, distinta del resto de la charla.

## Objetivo

Escuchar el stream en vivo, entender lo que se dice y, cuando se diga la contraseña (o cuando
aparezca el sorteo), **avisar y copiar la palabra al portapapeles**. El usuario la pega a mano.

## Requisitos funcionales

| ID  | Requisito | Prioridad |
|-----|-----------|-----------|
| RF1 | Capturar el audio del stream de Kick en vivo (canal configurable). | Alta |
| RF2 | Alternativa: capturar el audio del PC (loopback) si Kick bloquea la descarga directa. | Alta |
| RF3 | Transcribir en español, en local y gratis, con poco retraso (< 5 s). | Alta |
| RF4 | Mantener en memoria los últimos minutos de audio y de texto (la contraseña se puede decir **antes** de que salga el sorteo). | Alta |
| RF5 | Detectar la contraseña en el texto aunque la frase varíe ("la clave es…", "…es la contraseña", "pongan…"). | Alta |
| RF6 | Al detectar una candidata: notificación de Windows, sonido, copiar al portapapeles y mostrarla en consola con alternativas. | Alta |
| RF7 | Disparar un re-análisis más preciso de los últimos minutos con una tecla rápida. | Alta |
| RF8 | Disparar ese re-análisis automáticamente cuando se abre una ronda en el sitio de sorteos (URL configurable). | Alta (hecho) |
| RF9 | ~~Guardar un clip de audio en disco~~ → descartado: no guardar nada en disco. | — |
| RF10 | Herramienta para probar con VODs/grabaciones de sorteos pasados y ajustar las reglas. | Media |
| RF11 | Meter la contraseña confirmada en el formulario del sitio con la sesión del usuario (opcional). | Media (hecho) |

## Requisitos no funcionales

- **Todo local y gratis**: Whisper en la GPU (probado con 6 GB de VRAM), sin APIs de pago.
- La interacción con la web es opcional (`[autojoin]`) y usa la sesión del propio usuario.
- Windows 11, Python 3.11.
- Configurable por archivo (`config.toml`), sin tocar código: canal, URLs y textos del sitio incluidos.
- Respetar las reglas del sitio de sorteos y de las plataformas.

## Fuera de alcance (por ahora)

- Leer el chat de Kick (podría ser una fuente extra, ver `research.md`).
- Interfaz gráfica.

## Preguntas abiertas

1. ~~HTML del sorteo~~ → resuelto: el estado sale de una API pública JSON del sitio (ver `research.md` §4).
2. ~~¿Cuándo se dice la contraseña?~~ → normalmente **al principio** de la ronda, pocos segundos después de
   abrirse. Ver `research.md` §6.
3. ¿Distingue mayúsculas, tildes o espacios? A veces lo dice el streamer: "girasol en la mochila, **todo
   junto**". El bot copia la versión sin espacios cuando oye "todo junto" y muestra variantes sin tildes.
4. ¿Las secciones `no_subs` y `subs` usan la misma contraseña? (se abren a la vez).
