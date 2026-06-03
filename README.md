# LyPlex

Converts a LilyPond sheet music file (`.ly`) into a scrolling MP4 video with synchronized audio.

## What it does

- Compiles `.ly` → SVG strip + MIDI via LilyPond
- Correlates note anchors (SVG) with onset times (MIDI) to build a timing map
- Renders a scrolling video at any resolution with configurable overlays
- Synthesizes audio via FluidSynth + a soundfont
- Optional: metronome click track, count-in bars, watermark, fade in/out, bar numbers

## Requirements

**Python packages** (`pip install -r requirements.txt`):
```
mido, cairosvg, Pillow, lxml, wxPython
```

**External binaries** (must be on PATH or configured in GUI):
- [LilyPond 2.24](https://lilypond.org/download.html)
- [ffmpeg](https://ffmpeg.org/download.html)
- [FluidSynth](https://www.fluidsynth.org/)
- A General MIDI soundfont — [GeneralUser GS](https://schristiancollins.com/generaluser.php) recommended

## Usage

### GUI

```
python lyplex_gui.py
```

Pick a `.ly` file, a `.sf2` soundfont, configure overlays, click **Encode MP4**.

### CLI

```
python lyplex_tool.py score.ly soundfont.sf2 [output.mp4] [options]
```

Key options:

| Flag | Default | Description |
|------|---------|-------------|
| `--width` / `--height` | 1920 × 1080 | Output resolution |
| `--fps` | 30 | Frame rate |
| `--tempo BPM` | score tempo | Override tempo (requires `\tempo` in `.ly`) |
| `--volume-db DB` | 14.5 | Music volume boost in dB |
| `--fade-frames N` | 0 | Fade in/out frames (15 ≈ 0.5s at 30fps) |
| `--metronome` | off | Mix synthesized click track |
| `--count-in BARS` | 0 | Count-in bars before music |
| `--click-volume-db DB` | -3.0 | Click track level relative to music |
| `--watermark PATH` | none | Logo image (SVG/PNG/JPEG), corner position via `--watermark-position` |
| `--no-cursor` | — | Hide playback cursor |
| `--no-trail` | — | Hide note trail dots |
| `--no-highlight` | — | Hide active note highlight |
| `--cursor-color R,G,B` | 220,50,50 | Cursor line color |
| `--highlight-color R,G,B` | 50,120,220 | Highlight dot color |
| `--fill-height` | off | Pad strip to full output height |
| `--no-bar-numbers` | — | Hide bar numbers |
| `--no-bar-timing` | — | Note-level scroll instead of bar-level |
| `--lilypond PATH` | system PATH | LilyPond binary |
| `--ffmpeg PATH` | system PATH | ffmpeg binary |
| `--fluidsynth PATH` | system PATH | FluidSynth binary |

## Score format requirements

Your `.ly` file must:
1. Have a `\version "..."` declaration
2. Have a `\midi {}` block inside `\score` (for audio/timing)

LyPlex injects the single-strip paper layout and `\pointAndClickTypes` automatically — do not add them manually.

## Notes

- LilyPond 2.24 required; other versions untested
- Very long scores (>10 min) may use significant RAM for the strip PNG
- `\repeat volta` is automatically unfolded so the scroll covers the full piece

---

# LyPlex (Español — América Latina)

Convierte un archivo de partitura LilyPond (`.ly`) en un video MP4 con desplazamiento horizontal y audio sincronizado.

## Qué hace

- Compila `.ly` → tira SVG + MIDI mediante LilyPond
- Correlaciona los anclajes de notas (SVG) con los tiempos de inicio (MIDI) para construir un mapa de sincronización
- Renderiza un video con desplazamiento en cualquier resolución, con superposiciones configurables
- Sintetiza el audio con FluidSynth y un soundfont
- Opcional: pista de metrónomo, compases de cuenta regresiva, marca de agua, fundido de entrada/salida, números de compás

## Requisitos

**Paquetes de Python** (`pip install -r requirements.txt`):
```
mido, cairosvg, Pillow, lxml, wxPython
```

**Binarios externos** (deben estar en el PATH o configurarse desde la interfaz gráfica):
- [LilyPond 2.24](https://lilypond.org/download.html)
- [ffmpeg](https://ffmpeg.org/download.html)
- [FluidSynth](https://www.fluidsynth.org/)
- Un soundfont General MIDI — se recomienda [GeneralUser GS](https://schristiancollins.com/generaluser.php)

## Uso

### Interfaz gráfica (GUI)

```
python lyplex_gui.py
```

Seleccione un archivo `.ly`, un soundfont `.sf2`, configure las superposiciones y haga clic en **Encode MP4**.

### Línea de comandos (CLI)

```
python lyplex_tool.py score.ly soundfont.sf2 [output.mp4] [options]
```

Opciones principales:

| Parámetro | Por defecto | Descripción |
|-----------|-------------|-------------|
| `--width` / `--height` | 1920 × 1080 | Resolución de salida |
| `--fps` | 30 | Fotogramas por segundo |
| `--tempo BPM` | tempo de la partitura | Sobreescribe el tempo (requiere `\tempo` en el `.ly`) |
| `--volume-db DB` | 14.5 | Amplificación del volumen de la música en dB |
| `--fade-frames N` | 0 | Fotogramas de fundido de entrada/salida (15 ≈ 0.5s a 30fps) |
| `--metronome` | desactivado | Mezcla una pista de clic sintetizada |
| `--count-in BARS` | 0 | Compases de cuenta regresiva antes de la música |
| `--click-volume-db DB` | -3.0 | Nivel de la pista de clic relativo a la música |
| `--watermark PATH` | ninguno | Imagen de logo (SVG/PNG/JPEG); posición en la esquina mediante `--watermark-position` |
| `--no-cursor` | — | Oculta el cursor de reproducción |
| `--no-trail` | — | Oculta los puntos de rastro de notas |
| `--no-highlight` | — | Oculta el resaltado de la nota activa |
| `--cursor-color R,G,B` | 220,50,50 | Color de la línea del cursor |
| `--highlight-color R,G,B` | 50,120,220 | Color del punto de resaltado |
| `--fill-height` | desactivado | Rellena la tira hasta la altura total de salida |
| `--no-bar-numbers` | — | Oculta los números de compás |
| `--no-bar-timing` | — | Desplazamiento por nota en lugar de por compás |
| `--lilypond PATH` | PATH del sistema | Binario de LilyPond |
| `--ffmpeg PATH` | PATH del sistema | Binario de ffmpeg |
| `--fluidsynth PATH` | PATH del sistema | Binario de FluidSynth |

## Requisitos del formato de partitura

El archivo `.ly` debe:
1. Incluir una declaración `\version "..."`
2. Incluir un bloque `\midi {}` dentro de `\score` (para el audio y la sincronización)

LyPlex inyecta automáticamente el diseño de tira de papel en una sola línea y `\pointAndClickTypes` — no los agregue manualmente.

## Notas

- Se requiere LilyPond 2.24; otras versiones no han sido probadas
- Partituras muy largas (>10 min) pueden usar una cantidad significativa de RAM para el PNG de la tira
- `\repeat volta` se despliega automáticamente para que el desplazamiento cubra la pieza completa
