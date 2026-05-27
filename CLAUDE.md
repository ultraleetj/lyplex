# LyPlex — Project Notes

## What this is

Python pipeline + HTML preview for scrolling sheet music video from LilyPond sources.
Input: `.ly` file. Output: scrolling MP4 + self-contained HTML preview.

**Files:**
- `lyplex_tool.py` — core library: LilyPond subprocess, SVG/MIDI parsing, timing map, ffmpeg
- `lyplex_gui.py` — wxPython GUI front-end
- `lyplex_web.py` — generates self-contained HTML scroll preview

**Dependencies:** `python-ly`, `mido`, `cairosvg`, `Pillow`, `lxml`, `wxPython` (GUI only)
External binaries: `lilypond`, `ffmpeg`, `fluidsynth` (audio) — must be on PATH

---

## Pipeline overview

```
score.ly
  ↓ lilypond -dsvg -dpoint-and-click
score.svg  +  score.midi
  ↓ lxml (SVG parse)       ↓ mido (MIDI parse)
note elements + x-coords   note events + ms timing
  ↓ python-ly (parse .ly for source-position → beat mapping)
timing_map: [ {ms: N, x: PX}, ... ]
  ↓
  ├── lyplex_web.py  → score.html  (SVG embedded + JS scroll)
  └── lyplex_tool.py → PNG frames (cairosvg + Pillow pan) → ffmpeg → score.mp4
```

---

## LilyPond compile flags

```bash
lilypond -dsvg -dpoint-and-click score.ly
```

- `-dsvg` — SVG output (one file per page, or single strip — see paper config)
- `-dpoint-and-click` — embeds `textedit://file:LINE:COL` on every note element in SVG

Single-strip (scroll-friendly, recommended):
```lilypond
\paper {
  line-width = 9999\mm
  page-count = 1
  indent = 0
}
```
Produces one long horizontal SVG — camera pans left→right.

---

## SVG coordinate extraction

Each note element in SVG (with point-and-click) has:
- `xlink:href` or `href` = `textedit://FILEPATH:LINE:COL:ENDCOL`
- Ancestor `<g>` or `<a>` wraps the note glyph with a bounding box

Extract: `{(line, col): x_center}` for all note anchors.

---

## Timing map construction

1. `python-ly` (`pip install ly`) — parse `.ly`, walk music tree, get `(line, col) → beat_offset`
2. MIDI from LilyPond — `mido` reads tempo + note events → `beat_offset → ms`
3. Cross-reference: `(line,col) → beat → ms` + `(line,col) → x` → `ms → x`
4. Result: sorted list of `(ms, x_pixel)` — scroll positions over time

---

## HTML preview output

Self-contained single `.html` file:
- SVG embedded inline
- Timing map as JSON in `<script>`
- JS: `AudioContext` for timing clock, scroll via `element.scrollLeft` or `transform: translateX`
- MIDI playback: either embedded SF2 audio (base64) or link to generated WAV/MP3
- Play/pause button, tempo slider

No server needed — opens directly in browser.

---

## MP4 export

1. `cairosvg` renders SVG → high-DPI PNG (full strip)
2. `Pillow` crops each frame: `img.crop((x_offset, 0, x_offset+width, height))`
3. Frames piped to `ffmpeg` stdin as PNG sequence
4. Audio from `fluidsynth` CLI: `fluidsynth -F audio.wav soundfont.sf2 score.midi`
5. `ffmpeg -i frames.mp4 -i audio.wav -c:v libx264 -c:a aac output.mp4`

Resolution: user-configurable, must be multiples of 2 (ffmpeg requirement).

---

## GUI (lyplex_gui.py)

wxPython, single window:
- `.ly` file picker
- Soundfont picker (`.sf2`)
- Resolution fields (W × H)
- Tempo multiplier (scales timing map, does not re-render SVG)
- Output folder
- "Generate HTML" button — fast path, no audio render
- "Encode MP4" button — full pipeline
- Log output (streaming, carriage-return progress lines handled)
- "Open HTML" / "Show in Explorer" buttons after completion

---

## Known gaps / TODO

- [ ] Multi-page LilyPond output (paginated scroll) — harder than single strip
- [ ] Repeats in score: LilyPond MIDI unfolds repeats; SVG does not — sync breaks
- [ ] Lyrics / annotations in SVG: included automatically, no extra work needed
- [ ] Dynamics / hairpins: rendered by LilyPond, visible in SVG, no special handling
- [ ] Font embedding in cairosvg: verify Emmentaler/LilyPond fonts render correctly
