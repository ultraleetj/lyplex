# LyPlex

Turn a LilyPond sheet music file (`.ly`) into a scrolling MP4 video with synchronized audio. Main uses: sightreading practice videos, YouTube tutorial-style uploads, or just showing off a piece you typeset, maybe.

**[Download the latest Windows release](https://github.com/ultraleetj/lyplex/releases/latest)**

## How it works

LyPlex compiles your score three ways: once for the visual SVG strip, once for timing MIDI (scroll sync), and once for audio MIDI (what you actually hear). It correlates note positions in the SVG with onset times in the MIDI to build a timing map, then renders a smooth scrolling video at whatever resolution you want.

In short: you give it a `.ly` file, it gives you an MP4.

## Two ways to use it

**GUI (recommended for most people):** Download the Windows release zip, extract it anywhere, run `LyPlex.exe`. No Python required. Pick a `.ly` file, pick a soundfont, configure overlays, hit **Encode MP4**. That's it.

**CLI (requires Python):** Clone this repo, install dependencies, and run `lyplex_tool.py` directly from the command line. Useful for automation, batch processing, or if you prefer to script things. Requires Python 3.10+ and the packages listed below.

## Requirements

**For the portable GUI exe:** install LilyPond first, then just extract the zip and run. No Python, no pip, no drama.

**For the CLI or running from source** (`pip install -r requirements.txt`):
```
mido, cairosvg, Pillow, lxml, wxPython
```

**External binaries** (must be on PATH or set in the GUI. LyPlex will tell you loudly if one is missing):
- [LilyPond 2.24](https://lilypond.org/download.html) — **install this yourself.** There is no such thing as a free lunch, and bundling a full notation engraving engine on top of ffmpeg, FluidSynth, and a soundfont is the kind of decision that gets you ratio'd on the internet. Install it, put it on PATH (or point the GUI at it), and we're good.
- [ffmpeg](https://ffmpeg.org/download.html) — encodes the video (bundled in the portable zip)
- [FluidSynth](https://www.fluidsynth.org/) — synthesizes the audio (bundled in the portable zip)
- A General MIDI soundfont — [GeneralUser GS](https://schristiancollins.com/generaluser.php) is free and sounds great (also bundled)

## CLI usage

```
python lyplex_tool.py score.ly soundfont.sf2 [output.mp4] [options]
```

Key options:

| Flag | Default | Description |
|------|---------|-------------|
| `--width` / `--height` | 1920 x 1080 | Output resolution |
| `--fps` | 30 | Frame rate |
| `--tempo BPM` | score tempo | Override tempo (requires `\tempo` in `.ly`) |
| `--volume-db DB` | 14.5 | Music volume boost in dB |
| `--fade-frames N` | 0 | Fade in/out frames (15 ≈ 0.5s at 30fps) |
| `--metronome` | off | Mix a synthesized click track into the audio |
| `--count-in BARS` | 0 | Count-in bars before music starts |
| `--click-volume-db DB` | -3.0 | Click track level relative to music |
| `--watermark PATH` | none | Logo image (SVG/PNG/JPEG), corner position via `--watermark-position` |
| `--no-cursor` | off | Hide the playback cursor line |
| `--no-trail` | off | Hide past-beat trail dots |
| `--no-highlight` | off | Hide the active note highlight |
| `--cursor-color R,G,B` | 220,50,50 | Cursor line color |
| `--highlight-color R,G,B` | 50,120,220 | Highlight dot color |
| `--fill-height` | off | Pad strip to full output height (avoids letterboxing on short staves) |
| `--no-bar-numbers` | off | Hide bar numbers |
| `--no-bar-timing` | off | Scroll by individual note instead of by bar (can be jittery on fast passages) |
| `--lilypond PATH` | system PATH | Path to LilyPond binary |
| `--ffmpeg PATH` | system PATH | Path to ffmpeg binary |
| `--fluidsynth PATH` | system PATH | Path to FluidSynth binary |

## Score format requirements

Your `.ly` file must have:
1. A `\version "..."` declaration (LilyPond requires it; so does LyPlex)
2. A `\midi {}` block inside `\score` — this is how LyPlex gets timing and audio

LyPlex injects the single-strip paper layout and `\pointAndClickTypes` automatically. Don't add them manually or things will get weird.

## Observations

- LilyPond 2.24 required. Other versions are untested and may produce unexpected results.
- Very long scores (>10 min) can use significant RAM for the strip PNG. You've been warned.
- **Repeat handling:** if your score uses `\repeat volta`, `\repeat percent`, or already contains `\unfoldRepeats`, LyPlex will unfold all repeats so the scroll covers the full piece. Exception: if your score uses `\new ChordNames` (chord symbol staves), unfolding is skipped. Chord parts are typically written linearly and don't match the volta structure, so forcing unfold causes blank staves and audio/visual drift. In that case the score plays as written, repeats and all, like a musician who saw the repeat signs, decided today was not the day, and kept walking.

---

# LyPlex (Español — América Latina)

Convierte un archivo de partitura LilyPond (`.ly`) en un video MP4 con desplazamiento horizontal y audio sincronizado. Usos principales: videos de práctica para lectura a primera vista, publicaciones al estilo tutorial de YouTube, o simplemente para mostrar una pieza que tipografiaste, quizás.

**[Descargar la última versión para Windows](https://github.com/ultraleetj/lyplex/releases/latest)**

## Cómo funciona

LyPlex compila tu partitura de tres formas: una para la tira visual SVG, otra para el MIDI de sincronización (el desplazamiento) y otra para el MIDI de audio (lo que realmente se escucha). Luego correlaciona las posiciones de las notas en el SVG con los tiempos de inicio en el MIDI para construir un mapa de sincronización, y renderiza un video con desplazamiento suave en la resolución que quieras.

En pocas palabras: le das un archivo `.ly`, te devuelve un MP4.

## Dos formas de usarlo

**Interfaz gráfica (recomendada para la mayoría):** Descarga el zip de la última versión para Windows, extráelo donde quieras y ejecuta `LyPlex.exe`. No se necesita Python. Selecciona un archivo `.ly`, elige un soundfont, configura las superposiciones y presiona **Encode MP4**. Así de simple.

**Línea de comandos (requiere Python):** Clona este repositorio, instala las dependencias y ejecuta `lyplex_tool.py` directamente desde la terminal. Útil para automatización, procesamiento por lotes, o si prefieres trabajar con scripts. Requiere Python 3.10+ y los paquetes indicados más abajo.

## Requisitos

**Para el exe portable:** instala LilyPond primero, luego extrae el zip y ejecuta. Sin Python, sin pip, sin dramas.

**Para la línea de comandos o ejecutar desde el código fuente** (`pip install -r requirements.txt`):
```
mido, cairosvg, Pillow, lxml, wxPython
```

**Binarios externos** (deben estar en el PATH o configurarse desde la interfaz gráfica. LyPlex te avisará claramente si falta alguno):
- [LilyPond 2.24](https://lilypond.org/download.html) — **este lo instalas tú.** No existe el almuerzo gratis, y empaquetar un motor de tipografía musical completo encima de ffmpeg, FluidSynth y un soundfont es el tipo de decisión que te gana el odio colectivo de internet. Instálalo, ponlo en el PATH (o apunta la interfaz gráfica hacia él), y listo.
- [ffmpeg](https://ffmpeg.org/download.html) — codifica el video (incluido en el zip portable)
- [FluidSynth](https://www.fluidsynth.org/) — sintetiza el audio (incluido en el zip portable)
- Un soundfont General MIDI — [GeneralUser GS](https://schristiancollins.com/generaluser.php) es gratuito y suena muy bien (también incluido)

## Uso desde línea de comandos

```
python lyplex_tool.py score.ly soundfont.sf2 [output.mp4] [opciones]
```

Opciones principales:

| Parámetro | Por defecto | Descripción |
|-----------|-------------|-------------|
| `--width` / `--height` | 1920 x 1080 | Resolución de salida |
| `--fps` | 30 | Fotogramas por segundo |
| `--tempo BPM` | tempo de la partitura | Sobreescribe el tempo (requiere `\tempo` en el `.ly`) |
| `--volume-db DB` | 14.5 | Amplificación del volumen de la música en dB |
| `--fade-frames N` | 0 | Fotogramas de fundido de entrada/salida (15 ≈ 0.5s a 30fps) |
| `--metronome` | desactivado | Mezcla una pista de clic sintetizada en el audio |
| `--count-in BARS` | 0 | Compases de cuenta regresiva antes de que empiece la música |
| `--click-volume-db DB` | -3.0 | Nivel de la pista de clic relativo a la música |
| `--watermark PATH` | ninguno | Imagen de logo (SVG/PNG/JPEG); posición en la esquina mediante `--watermark-position` |
| `--no-cursor` | desactivado | Oculta la línea del cursor de reproducción |
| `--no-trail` | desactivado | Oculta los puntos de rastro de notas pasadas |
| `--no-highlight` | desactivado | Oculta el resaltado de la nota activa |
| `--cursor-color R,G,B` | 220,50,50 | Color de la línea del cursor |
| `--highlight-color R,G,B` | 50,120,220 | Color del punto de resaltado |
| `--fill-height` | desactivado | Rellena la tira hasta la altura total de salida (evita barras negras en pentagramas cortos) |
| `--no-bar-numbers` | desactivado | Oculta los números de compás |
| `--no-bar-timing` | desactivado | Desplazamiento por nota en lugar de por compás (puede verse irregular en pasajes rápidos) |
| `--lilypond PATH` | PATH del sistema | Ruta al binario de LilyPond |
| `--ffmpeg PATH` | PATH del sistema | Ruta al binario de ffmpeg |
| `--fluidsynth PATH` | PATH del sistema | Ruta al binario de FluidSynth |

## Requisitos del formato de partitura

El archivo `.ly` debe tener:
1. Una declaración `\version "..."` (LilyPond la exige; LyPlex también)
2. Un bloque `\midi {}` dentro de `\score` — así es como LyPlex obtiene la sincronización y el audio

LyPlex inyecta automáticamente el diseño de tira de papel en una sola línea y `\pointAndClickTypes`. No los agregues manualmente o las cosas se van a poner raras.

## Observaciones

- Se requiere LilyPond 2.24. Otras versiones no han sido probadas y pueden dar resultados inesperados.
- Partituras muy largas (>10 min) pueden usar una cantidad significativa de RAM para el PNG de la tira. Considera esto una advertencia formal.
- **Manejo de repeticiones:** si la partitura usa `\repeat volta`, `\repeat percent`, o ya contiene `\unfoldRepeats`, LyPlex desplegará todas las repeticiones para que el desplazamiento cubra la pieza completa. Excepción: si la partitura usa `\new ChordNames` (pentagrama de cifrado armónico), el despliegue se omite. Las partes de acordes suelen estar escritas linealmente y no coinciden con la estructura de las casillas, por lo que forzar el despliegue genera pentagramas vacíos y desincronización entre audio y video. En ese caso la partitura se toca tal como está escrita, signos de repetición incluidos, como un músico que los vio, decidió que hoy no era el día, y siguió de largo.
