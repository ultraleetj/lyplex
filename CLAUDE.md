# LyPlex — Project Notes

## What this is

Python pipeline + optional HTML preview for scrolling sheet music video from LilyPond sources.
Input: `.ly` file. Output: scrolling MP4 (primary). HTML preview is secondary / deprioritized.

**Target LilyPond version: 2.24**

**Files:**
- `lyplex_tool.py` — core library: LilyPond subprocess, SVG/MIDI parsing, timing map, ffmpeg
- `lyplex_gui.py` — wxPython GUI front-end
- `lyplex_web.py` — generates self-contained HTML scroll preview (low priority)

**Dependencies:** `mido`, `cairosvg`, `Pillow`, `lxml`, `wxPython` (GUI only)
External binaries: `lilypond`, `ffmpeg`, `fluidsynth` (audio) — must be on PATH

`python-ly` dropped: it is a syntax parser only, cannot compute beat offsets. Not used.

---

## Pipeline overview

```
score.ly
  ↓ lilypond -dsvg -dpoint-and-click
score.svg  +  score-timing.midi  +  score-audio.midi
  ↓ lxml (SVG parse)       ↓ mido (MIDI parse)
note anchors + x-coords    note_on events + tick→ms timing
  ↓ order-based correlation (group by beat position)
timing_map: [ {ms: N, x: PX}, ... ]
  ↓
  ├── lyplex_web.py  → score.html  (SVG + JS scroll) [low priority]
  └── lyplex_tool.py → PNG frames (cairosvg + Pillow pan) → ffmpeg → score.mp4
```

---

## LilyPond compile flags

```bash
lilypond -dsvg -dpoint-and-click score.ly
```

- `-dsvg` — SVG output
- `-dpoint-and-click` — embeds `textedit://FILEPATH:LINE:COL:ENDCOL` on every note element in SVG
- LilyPond embeds full absolute paths in textedit:// URIs — no special handling needed on Windows

Single-strip layout (scroll-friendly, required):
```lilypond
\paper {
  line-width = 9999\mm
  page-count = 1
  indent = 0
}
```
Produces one long horizontal SVG strip — camera pans left→right.

---

## Patched compile variants

Three variants compiled from patched `.ly` copies. User never manages patches manually.

| Variant | `~` stripped | `\unfoldRepeats` stripped | Purpose |
|---------|-------------|--------------------------|---------|
| SVG | yes + `\pointAndClickTypes #'note-event` | — | Visual strip, no ties, note anchors only |
| Timing MIDI | yes | yes | Scroll sync — 1:1 with SVG anchors |
| Audio MIDI | no | no | Original score, full audio with repeats |

**Ties (`~` stripping):**
Stripping `~` from SVG source removes tie curves visually and gives one SVG anchor per notehead.
Stripping from timing MIDI source gives one note_on per notehead → 1:1 anchor↔event grouping.
Pedagogical bonus: video shows notes without ties (students read clean noteheads first).

**Repeats:**
LilyPond without `\unfoldRepeats` plays MIDI straight through once, as if no repeats exist.
This naturally stays in sync with SVG notation (which also shows each section once).
Dual MIDI only matters when audio needs to play repeats (i.e., when original has `\unfoldRepeats`).
`lyplex_tool.py` detects `\unfoldRepeats` in the midi block via regex to decide if audio MIDI differs.

---

## SVG coordinate extraction

**Inject `\pointAndClickTypes #'note-event`** into the patched SVG `.ly` (alongside `~` stripping).
LilyPond then emits `<a>` anchors ONLY for `note-event` grobs — rests (`rest-event`), dynamics,
slurs, articulations get no anchor. Eliminates all manual glyph-type filtering.

Anchor format (from `scm/output-svg.scm`):
```xml
<a style="color:inherit;" xlink:href="textedit://FILE:LINE:CHR:COL">
  <path .../>   <!-- notehead glyph path -->
</a>
```
URI has 4 fields: FILE, LINE, CHR (char offset), COL (end column). Windows backslashes already
converted to `/` by LilyPond before embedding — no special handling needed.

The `<a>` is nested inside `<g transform="translate(x, y)">` ancestors (staff, system, page offsets).
**x position**: walk ancestor chain, accumulate all `translate(x, y)` x-values → absolute x in
LilyPond SVG units (1 unit = 1.7573 mm, set by `lily-unit-length`).

Extract: `[(line, chr, x_absolute), ...]` for all `<a xlink:href="textedit://...">` elements.

---

## MIDI parsing details

**Multi-track:** LilyPond outputs one MIDI track per staff/instrument. Collect note_on events
from ALL tracks, merge by tick before beat grouping.

**Tempo changes:** MIDI `SET_TEMPO` meta events appear on track 0. Accumulate them for correct
tick→ms conversion — do not assume constant tempo. `mido` provides `MidiFile.ticks_per_beat`;
iterate all messages in order, tracking current tempo and elapsed ticks.

```python
def ticks_to_ms(midi_file):
    """Returns list of (tick, ms) tempo-map checkpoints."""
    tempo = 500000  # default: 120 BPM
    checkpoints = [(0, 0.0)]
    elapsed_ticks = 0
    elapsed_ms = 0.0
    for msg in mido.merge_tracks(midi_file.tracks):
        elapsed_ticks += msg.time
        if msg.type == 'set_tempo':
            elapsed_ms += mido.tick2second(msg.time, midi_file.ticks_per_beat, tempo) * 1000
            tempo = msg.tempo
            checkpoints.append((elapsed_ticks, elapsed_ms))
    return checkpoints
```

**xlink namespace:** LilyPond SVG uses `xlink:href` (confirmed in `scm/output-svg.scm`).
lxml requires full namespace URI: `{http://www.w3.org/1999/xlink}href`. Plain `href` finds nothing.

```python
XLINK = 'http://www.w3.org/1999/xlink'
anchors = svg_root.findall(f'.//{{{XLINK}}}a[@{{{XLINK}}}href]', ...)
# or simpler:
for a in svg_root.iter('{http://www.w3.org/2000/svg}a'):
    href = a.get('{http://www.w3.org/1999/xlink}href', '')
```

---

## Timing map construction

**Core problem:** SVG gives `(line,col) → x_pixel`. MIDI gives `tick → ms`. No direct link.

**Approach: order-based beat grouping**

1. Parse SVG → list of `(x_pixel, line, col)` sorted by x (left→right = time order)
2. Parse timing MIDI with `mido` → list of `(tick, pitch)` note_on events sorted by tick
3. Group SVG anchors by x position (notes at same x = same beat/chord)
4. Group MIDI note_ons by tick (same tick = same chord)
5. Zip groups in order: `beat_groups[i].x ↔ midi_groups[i].tick`
6. Apply MIDI tempo map: `tick → ms`
7. Result: `timing_map = [(ms, x_pixel), ...]` sorted by ms, deduplicated

**Chord/voice handling:**
- Multiple noteheads at same x → one entry in timing_map (one x per beat moment)
- Multi-voice at same beat: use x from the voice with the longer note value (drives scroll)
- Chords: treat as single moment, take upper voice / any one notehead x

**Grace notes:** generate MIDI note_on events slightly before their following main note tick
(anticipation). Order-based grouping handles this naturally — grace tick < main tick, both in order.
Exception: at piece start, LilyPond warns "going back in MIDI time" — grace note gets tick 0
same as first main note. Strategy: after grouping, if two consecutive groups share the same tick,
merge them and keep the rightmost x (the main note position). Grace note scroll position is
irrelevant — cursor barely moves in the tiny anticipation window.

**Validation:** `len(svg_beat_groups) == len(midi_beat_groups)` — assert this, log mismatch.

---

## Scroll behavior

Matches MuseScore / Finale "follow playback" style:
- **Cursor position:** fixed at ~45% from left edge of viewport (shows upcoming music)
- **Scroll type:** smooth continuous interpolation between note onsets — never jumps
- **Math:**

```python
# At playback time T (ms):
i = bisect(timing_map, T, key=lambda e: e.ms) - 1
i = clamp(i, 0, len(timing_map) - 2)
progress = (T - timing_map[i].ms) / (timing_map[i+1].ms - timing_map[i].ms)
score_x = timing_map[i].x + (timing_map[i+1].x - timing_map[i].x) * progress
scroll_offset = max(0, score_x - viewport_width * 0.45)
```

For MP4 frames: sample `scroll_offset` at each frame timestamp, crop PNG strip accordingly.
For HTML: drive via `requestAnimationFrame`, set `element.scrollLeft = scroll_offset`.

---

## SVG → pixel coordinate conversion

Timing map x values are in SVG viewBox units (LilyPond internal units).
Pillow crop needs pixel coordinates. Conversion:

```python
# Parse from SVG root element:
#   width="Wmm"  height="Hmm"  viewBox="vx vy vw vh"
svg_width_mm  = parse_mm(svg.attrib['width'])   # e.g. "450.23mm" → 450.23
viewbox_width = float(svg.attrib['viewBox'].split()[2])
render_dpi    = output_H / svg_height_mm * 25.4  # scale so strip height == output height
px_per_mm     = render_dpi / 25.4
px_per_svgu   = svg_width_mm * px_per_mm / viewbox_width

# Convert timing map:
x_px = x_svgu * px_per_svgu
```

cairosvg render call:
```python
cairosvg.svg2png(url=svg_path, write_to=png_path, dpi=render_dpi)
```
`render_dpi` derived from output height — strip rendered once at correct scale so
`strip_img.height == output_H` exactly. No resize step needed.

---

## MP4 export

1. Compute `render_dpi` from output height + SVG height-in-mm (see above)
2. `cairosvg` renders SVG strip → full-strip PNG at `render_dpi` (rendered once)
3. For each frame N at time `N / fps` seconds:
   - Compute `scroll_offset_svgu` via timing map interpolation
   - `scroll_offset_px = scroll_offset_svgu * px_per_svgu`
   - `frame = strip_img.crop((scroll_offset_px, 0, scroll_offset_px + W, H))`
4. Frames piped to `ffmpeg` stdin as PNG sequence
5. Audio: `fluidsynth -F audio.wav soundfont.sf2 score-audio.midi`
6. Mux: `ffmpeg -framerate FPS -i pipe:0 -i audio.wav -c:v libx264 -c:a aac output.mp4`

**Frame rate:** 30 fps default, configurable. Must produce even resolution (ffmpeg requirement).
**Resolution:** user-configurable W × H, both must be multiples of 2.

---

## HTML preview output (low priority)

Self-contained single `.html` file:
- SVG embedded inline
- Timing map as JSON in `<script>`
- JS: `requestAnimationFrame` timing clock, scroll via `element.scrollLeft`
- Audio: link to pre-rendered WAV/MP3 (SF2 base64 impractical — files are 100MB+)
- Play/pause button, tempo slider

No server needed — opens directly in browser.

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

## Strip PNG memory

Full-strip PNG can be very large for long scores (10 min @ 1080px tall ≈ 200MB+).
Pillow loads full image into RAM for cropping. Acceptable for typical teaching pieces (2–5 min).
For very long scores: tile the strip render and stitch, or use cairosvg region rendering.
Document as a known limitation; defer tiling until needed.

---

## Patching strategy

Patched `.ly` files written to `tempfile.mkdtemp()`. LilyPond run in that dir → outputs
`<basename>.svg` and `<basename>.midi` alongside patched source.

**`~` stripping:** `re.sub(r'~', '', source)` — safe. `~` is exclusively ties; never appears in markup.

**`\pointAndClickTypes #'note-event` injection:** insert after the `\version "..."` line.
Must be top-level, not inside `\score {}` or `\book {}`. Regex: find `\version "..."` line, append after it.

**LilyPond output naming:** single-page output → `<basename>.svg` (no page suffix).
With `page-count = 1` paper setting we always get one file.

---

## Upstream source references

Key files in `upstream/lilypond/` for implementation reference:

| File | What it tells us |
|------|-----------------|
| `scm/output-svg.scm` | Anchor format (`<a xlink:href="textedit://...">`), grob-cause logic, coordinate transforms |
| `scm/framework-svg.scm` | SVG width/height in mm, viewBox in LilyPond units, `output-scale = unit-length` |
| `lily/point-and-click.cc` | `textedit://FILE:LINE:CHR:COL` URI construction |
| `scm/define-event-classes.scm` | Event hierarchy: `note-event` ≠ `rest-event`, `multi-measure-rest-event` |
| `scm/midi.scm` | MIDI instrument names, channel assignments |
| `input/regression/point-and-click-types.ly` | `\pointAndClickTypes #'note-event` usage example |

---

## Known gaps / TODO

- [ ] Grace notes at piece start: merge tick-0 collisions (grace + main note both at tick 0)
- [ ] Strip PNG memory: document 2–5 min limit; tiling deferred
- [ ] Scroll clamp: before first note → offset=0; after last note → hold last position
- [x] `~` stripping: `re.sub(r'~', '', source)` — safe, `~` is exclusively ties in practice
- [ ] `cluster-note-event` excluded by `\pointAndClickTypes #'note-event` — clusters get no anchor (rare, deferred)
- [ ] Multi-staff (piano): noteheads at same beat share same x across staves — no special handling needed
- [ ] Multi-page LilyPond output (paginated scroll) — harder than single strip; deferred
- [ ] Font embedding in cairosvg: verify Emmentaler/LilyPond fonts render correctly
- [ ] Lyrics / annotations in SVG: included automatically by LilyPond, no extra work
- [ ] Dynamics / hairpins: rendered by LilyPond, visible in SVG, no special handling
