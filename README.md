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
