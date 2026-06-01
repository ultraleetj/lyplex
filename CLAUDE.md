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

`python-ly` dropped: syntax parser only, cannot compute beat offsets.

---

## Pipeline overview

```
score.ly
  ↓ lilypond --svg -dpoint-and-click -dno-use-paper-size-for-page
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
lilypond --svg -dpoint-and-click -dno-use-paper-size-for-page score.ly
```

- `--svg` — SVG output
- `-dpoint-and-click` — embeds `textedit://FILEPATH:LINE:COL:ENDCOL` on every note element in SVG
- `-dno-use-paper-size-for-page` — SVG width/height = actual content extent, not paper-width.
  Default `use-paper-size-for-page = #t` (`scm/lily.scm:477`) makes SVG = full paper-width even
  if music is shorter → wasted render memory. This flag disables that (`scm/page.scm:286-291`).
- LilyPond embeds full absolute paths in textedit:// URIs — no special handling needed on Windows

Single-strip layout (scroll-friendly, required):
```lilypond
\paper {
  system-count = 1
  paper-width = 9999\mm
  line-width = 9989\mm
  paper-height = 250\mm
  top-margin = 5\mm
  bottom-margin = 5\mm
  indent = 0
}
```
`system-count = 1` forces all music onto one horizontal strip. `line-width` must be ≤ `paper-width`;
both must be set or LilyPond warns and reverts to defaults. 9999mm ≈ 20 min at 120 BPM in 4/4.

**Auto-ragging:** single-system scores auto-use natural note spacing without `ragged-right = ##t`
(`lily/constrained-breaking.cc:142-148`). Combined with `-dno-use-paper-size-for-page`, SVG width
= exact music content width.

---

## Patched compile variants

Three variants compiled from patched `.ly` copies. User never manages patches manually.

| Variant | `~` stripped | `\unfoldRepeats` stripped | Purpose |
|---------|-------------|--------------------------|---------|
| SVG | yes + `\pointAndClickTypes #'(note-event cluster-note-event)` | — | Visual strip, no ties, note anchors only |
| Timing MIDI | yes | yes | Scroll sync — 1:1 with SVG anchors |
| Audio MIDI | no | no | Original score, full audio with repeats |

**Ties:** `~` is exclusively `TieEvent` (`ly/declarations-init.ly:85`) — `re.sub(r'~', '', source)`
is safe. Stripping gives one SVG anchor per notehead and one MIDI note_on per notehead → 1:1 grouping.

**Repeats:** without `\unfoldRepeats` LilyPond plays MIDI straight through once, staying in sync
with SVG. Dual MIDI needed only when source has `\unfoldRepeats`. Detection: `re.search(r"\\unfoldRepeats\b", source)` scans full source. `\unfoldRepeats` wraps score/music (not `\midi {}` blocks);
takes optional type: `volta`, `tremolo`, `percent`; empty = unfold all (`ly/music-functions-init.ly:2635`).

---

## SVG coordinate extraction

**Inject `\pointAndClickTypes #'(note-event cluster-note-event)`** after the `\version "..."` line
(top-level only). LilyPond emits `<a>` anchors only for note-event and cluster-note-event grobs.
`ClusterSpannerBeacon` (not ClusterSpanNote) receives cause event → anchors confirmed working
(`lily/cluster-engraver.cc:110`). Accepts list syntax: `symbol-list-or-symbol?` (`scm/c++.scm:189`).

Anchor format (`scm/output-svg.scm`):
```xml
<a style="color:inherit;" xlink:href="textedit://FILE:LINE:CHR:COL">
  <g transform="translate(x,y)">  ← absolute x in LilyPond SVG units
    <path .../>
  </g>
</a>
```
URI: 4 fields FILE:LINE:CHR:COL. Windows backslashes converted to `/` by LilyPond.

`<a>` may be nested inside ancestor `<g>` elements (`start-group-node`, `scm/output-svg.scm:76-83`).
**Translate is still absolute:** offset accumulates through the stencil tree before `grob-cause`
(`lily/stencil-interpret.cc:40-43`) — no need to sum ancestor `<g>` transforms.

**unit-length:** default 1 unit = 1.7573 mm (5pt at 20pt staff size). Changes with
`set-global-staff-size`. Implementation derives `px_per_svgu` from SVG `width` attribute vs
`viewBox` — robust to staff size changes.

**xlink namespace:** lxml requires `{http://www.w3.org/1999/xlink}href`. Plain `href` finds nothing.

Extract: `[(line, chr, x_absolute), ...]` for all `<a xlink:href="textedit://...">` elements.

---

## MIDI parsing details

**Multi-track:** one track per staff. Collect note_on events from ALL tracks, merge by tick.

**Tempo:** `SET_TEMPO` events guaranteed on track 0 — `Control_track_performer`
(`lily/control-track-performer.cc:50-87`) writes all tempo, time-sig, and marker events to
the control track (always track 0). Accumulate for correct tick→ms conversion; don't assume
constant tempo. Use `mido.merge_tracks()` iterating all messages; on `set_tempo` update and checkpoint.

**Time signature:** also on track 0 via control track. Read `time_signature` meta for bar-timing.

---

## Timing map construction

**Core problem:** SVG gives `(line,col) → x`. MIDI gives `tick → ms`. No direct link.

**Order-based beat grouping:**
1. SVG anchors → `(x, line, col)` sorted by x (left→right = time)
2. MIDI note_ons → `(tick, pitch)` sorted by tick
3. Group SVG by x; group MIDI by tick
4. Zip groups in order: `group[i].x ↔ group[i].tick`
5. Apply tempo map: tick → ms
6. Result: `[(ms, x), ...]` sorted by ms, deduplicated

**Grace notes:** `lily/midi-walker.cc` clamps negative delta-ticks to 0 → grace+main collapse to
one MIDI group while SVG has two. When `svg_count > midi_count`: repeatedly merge the consecutive
SVG pair with smallest x-gap (grace sits just left of main). Keep rightmost x after merge.

**Bar-level timing (default):** smoother scroll for fast passages. Bar x-positions interpolated
from note anchors. Bar start ticks: `0, ticks_per_bar, 2×ticks_per_bar, ...` where
`ticks_per_bar = ticks_per_beat × numerator × 4 / denominator`. `--no-bar-timing` to revert.

**`\pointAndClickTypes #'bar-event` is NOT viable:** BarLine grob created with `SCM_EOL` cause
(`lily/bar-engraver.cc:530`) → grob-cause returns empty → no anchor ever emitted.

---

## Scroll behavior

- Cursor fixed at ~45% from left (shows upcoming music)
- Smooth interpolation between note onsets

```python
# At playback time T (ms):
i = bisect(timing_map, T, key=lambda e: e.ms) - 1
i = clamp(i, 0, len(timing_map) - 2)
progress = (T - timing_map[i].ms) / (timing_map[i+1].ms - timing_map[i].ms)
score_x = timing_map[i].x + (timing_map[i+1].x - timing_map[i].x) * progress
scroll_offset = max(0, score_x - viewport_width * 0.45)
```

---

## SVG → pixel coordinate conversion

```python
# From SVG root: width="Wmm" height="Hmm" viewBox="vx vy vw vh"
svg_width_mm  = parse_mm(svg.attrib['width'])
viewbox_width = float(svg.attrib['viewBox'].split()[2])
render_dpi    = output_H / svg_height_mm * 25.4   # strip height == output height
px_per_svgu   = svg_width_mm * (render_dpi / 25.4) / viewbox_width
x_px = x_svgu * px_per_svgu
```

`cairosvg.svg2png(url=svg_path, write_to=png_path, dpi=render_dpi)` — rendered once, no resize.

---

## MP4 export

1. Render SVG → full-strip PNG via cairosvg at `render_dpi` (once)
2. Per frame: `strip_img.crop((scroll_offset_px, 0, scroll_offset_px + W, H))`
3. Pipe PNG frames to ffmpeg stdin
4. Audio: `fluidsynth -F audio.wav soundfont.sf2 score-audio.midi`
5. Mux: `ffmpeg -framerate FPS -i pipe:0 -i audio.wav -c:v libx264 -c:a aac output.mp4`

30 fps default. W × H must be multiples of 2.

**Strip PNG memory:** 10 min @ 1080px ≈ 200MB+. Pillow loads full strip. Acceptable for teaching
pieces (2–5 min). Warns at >400 MB estimate. Tiling deferred.

---

## Patching strategy

Patched `.ly` → `tempfile.mkdtemp()`. LilyPond outputs `<basename>-1.svg` and `<basename>.midi`.

- **`~` stripping:** `re.sub(r'~', '', source)` — safe (only TieEvent)
- **`\pointAndClickTypes` injection:** after `\version "..."` line, top-level
- **`\unfoldRepeats` stripping:** `re.sub(r"\\unfoldRepeats\b", "", source)`
- **`system-count = 1`** in paper block → always one SVG page → always `<basename>-1.svg`

---

## Metronome click track (IMPLEMENTED)

Opt-in `metronome=False` on `generate_mp4`. Python PCM synthesis (no extra dependencies).
Beat positions from timing MIDI tempo map. Beat 1 accented (higher freq + amplitude).
Click WAV mixed into audio via ffmpeg `amix` filter. `MetronomeDialog` in GUI exposes
waveform, freq, duration, amplitude, count-in bars per click type.

---

## HTML preview output (low priority, not started)

Single `.html`: SVG inline + timing map JSON + JS `requestAnimationFrame` scroll + audio link.

---

## GUI (lyplex_gui.py)

wxPython single window: .ly picker, SF2 picker, W×H resolution, tempo multiplier, output folder,
Generate HTML / Encode MP4 buttons, streaming log, Open/Explorer buttons after completion.
`PipelineConfig` dataclass passed to `_run_pipeline`. `MetronomeDialog`, `WatermarkDialog` for
overlay options. Accessible: `name=` on all controls, StaticText before each, status bar.

---

## Design decisions

- **No `\version`:** abort with clear error
- **No SF2/fluidsynth:** hard error before pipeline starts
- **svg > midi groups:** merge closest consecutive SVG pair (grace note case); keep rightmost x
- **svg < midi groups:** warn, truncate extra MIDI events
- **Multi-staff timing:** all staves used for SVG anchor grouping — `_group_by_value` collapses
  same-beat anchors via `round(x, 2)`. MIDI driving track = staff with longest total duration.

---

## Implementation status

| File | Status |
|------|--------|
| `lyplex_tool.py` | Done — full pipeline |
| `lyplex_gui.py` | Done — full GUI |
| `lyplex_web.py` | Not started (low priority) |

`lyplex_tool.py`: SVG+MIDI+audio compile, bar-level timing map, grace note reconciliation,
cluster-note-event anchors, memory warning, overlays (cursor/highlight/trail/watermark/bands),
metronome click, fade in/out, CLI with `--no-bar-timing`.

`lyplex_gui.py`: PipelineConfig dataclass, MetronomeDialog, WatermarkDialog, all overlay checkboxes/
color pickers, accessible controls.

---

## Upstream source references

| File | What it tells us |
|------|-----------------|
| `scm/output-svg.scm` | Anchor format, grob-cause logic, coordinate transforms, start-group-node |
| `scm/framework-svg.scm` | SVG width/height = stencil extent × output-scale; page-count drives multi-file output |
| `lily/paper-book.cc` | `output_stencils`: one SVG file per stencil (page), independent of system-count |
| `scm/page.scm` | `make-page-stencil`: x-extent = content unless `use-paper-size-for-page` |
| `scm/lily.scm` | `use-paper-size-for-page` defaults `#t` (line 477) |
| `lily/constrained-breaking.cc` | Single-system auto-ragging (lines 142-148) |
| `scm/define-paper-variables.scm` | `system-count`, `ragged-right`, `line-width` definitions |
| `lily/point-and-click.cc` | `textedit://FILE:LINE:CHR:COL` URI construction |
| `scm/define-event-classes.scm` | `note-event` ≠ `rest-event` ≠ `multi-measure-rest-event` |
| `lily/midi-walker.cc` | Grace note delta-tick clamping → tick-0 collision |
| `lily/control-track-performer.cc` | Tempo/time-sig/marker always on track 0 (lines 50-87) |
| `lily/stencil-interpret.cc` | Translate offset accumulation → SVG translate is absolute (lines 40-43) |
| `lily/cluster-engraver.cc` | ClusterSpannerBeacon gets cause event (line 110) |
| `ly/declarations-init.ly` | `~` = TieEvent only (line 85) |
| `ly/music-functions-init.ly` | `\unfoldRepeats` signature: optional type + music (lines 2635-2646) |
| `ly/property-init.ly` | `\pointAndClickTypes` accepts `symbol-list-or-symbol?` (line 683) |
| `scm/c++.scm` | `symbol-list-or-symbol?` predicate (lines 189-192) |
| `input/regression/point-and-click-types.ly` | `\pointAndClickTypes` usage example |

---

## Known gaps / TODO

- [x] All implementation gaps resolved (grace notes, strip memory, scroll clamp, tie stripping,
  cluster anchors, multi-staff, font fallback, mismatch reconciliation, metronome)
- [x] Bug fix: `_build_audio_cmd` — swapped `adelay` after `atempo` so music delay stays correct
  when `tempo_multiplier != 1.0` with metronome count-in (`lyplex_tool.py:_build_audio_cmd`)

**Multi-page SVG — IMPLEMENTED (upstream-verified):**
`system-count = 1` constrains *line* breaking only (`lily/page-breaking.cc:796-808`). Page breaking
is independent — `scm/framework-svg.scm` produces one SVG per stencil. Multiple SVG files can
appear when:
  - Score has explicit `\pageBreak`
  - Titles/headers consume vertical space beyond `paper-height`
  - System height + margins > paper-height

LilyPond SVG naming (`scm/framework-svg.scm:119-120`):
  - Single page → `<basename>.svg` (no suffix)
  - Multi-page → `<basename>-1.svg`, `<basename>-2.svg`, ... (1-indexed)

`compile_svg` returns `list[Path]` sorted by page number. `generate_mp4` extracts anchors
from all pages with cumulative x-offsets, crops only last page, renders each page PNG and
concatenates horizontally with Pillow. `px_per_svgu` is constant across pages (same compile).

- [x] Multi-page SVG: full horizontal concatenation implemented

**TODO — vertical fill / fit-to-height option:**
Currently `_crop_strip_height` auto-crops content to its natural height (e.g. 64px for
single-staff at 360px requested). Useful for tight display, but awkward in video editors
that expect a fixed output resolution (e.g. 1080p timeline).

Add `fill_height: bool = False` (or `fit_height`) parameter to `generate_mp4`:
- `False` (default) — current behaviour: crop to content, output is content-height tall
- `True` — pad cropped content to the requested `height` using a white (or configurable)
  background, centring the strip vertically. Output is always exactly `width × height`.

Implementation: after `_crop_strip_height`, if `fill_height`:
  ```python
  canvas = Image.new("RGB", (strip_img.width, height), (255, 255, 255))
  y_offset = (height - strip_img.height) // 2
  canvas.paste(strip_img, (0, y_offset))
  strip_img = canvas
  height = canvas.height  # already == requested height
  ```
Expose in GUI as checkbox "Fit to output height" next to resolution fields.
