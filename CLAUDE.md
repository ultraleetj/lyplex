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
  ↓ lilypond --svg -dpoint-and-click
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
lilypond --svg -dpoint-and-click score.ly
```

- `--svg` — SVG output
- `-dpoint-and-click` — embeds `textedit://FILEPATH:LINE:COL:ENDCOL` on every note element in SVG
- LilyPond embeds full absolute paths in textedit:// URIs — no special handling needed on Windows

Single-strip layout (scroll-friendly, required):
```lilypond
\paper {
  paper-width = 5000\mm
  line-width = 4990\mm
  paper-height = 250\mm
  top-margin = 5\mm
  bottom-margin = 5\mm
  indent = 0
}
```
`line-width` must be ≤ `paper-width`; setting only `line-width` triggers LilyPond's
"systems go off page" warning and it reverts to defaults. Both must be set.
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

In LilyPond 2.24, `<a>` is a **direct child of `<svg>` root** and contains a
`<g transform="translate(x, y)">` child — the translate is INSIDE the anchor, not outside it.
(Older versions nested `<a>` inside `<g>` ancestors; that structure no longer applies.)
**x position**: read `translate(x, y)` from the first child `<g>` of the `<a>` element → absolute x in
LilyPond SVG units (1 unit = 1.7573 mm, set by `lily-unit-length`).
Confirmed in `scm/output-svg.scm`: `settranslation` emits `<g transform="translate(x,y)">` and
the point-and-click anchor opens before it, wrapping it as a child.

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

**Grace notes:** normally produce a separate MIDI beat group at a tick slightly before the main
note — order-based grouping handles this naturally. Exception: `lily/midi-walker.cc` clamps
negative delta-ticks to 0 (the "Going back in MIDI time" error path), collapsing grace+main into
one MIDI beat group while SVG still has two separate anchor groups (grace visible left of main).

**Reconciliation:** when `len(svg_groups) > len(midi_groups)`, repeatedly merge the consecutive
SVG pair with the smallest x-gap (grace note sits just left of its main note → smallest gap).
After merging, keep the rightmost x (main note position) as the scroll target. Grace note scroll
position is irrelevant — cursor barely moves in the tiny anticipation window. Grace notes remain
visible in the SVG strip.

**Validation:** warn and reconcile on count mismatch rather than asserting.

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
- Tempo multiplier (scales timing map + ffmpeg atempo; does not re-render SVG)
- Output folder
- "Generate HTML" button — fast path, no audio render (disabled until lyplex_web.py done)
- "Encode MP4" button — full pipeline, runs in background thread
- Log output (streaming, carriage-return progress lines handled)
- "Open HTML" / "Show in Explorer" buttons after completion

**Accessibility (mirrors neothesia_gui.py patterns):**
- `name=` on every interactive control (Windows UIA accessible name)
- `StaticText` labels created before their controls (z-order = UIA LabeledBy)
- `CreateStatusBar()` with pipeline status messages
- `_on_char_hook` + `_focusable()` for Tab/Shift+Tab cycling within the panel

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

**LilyPond output naming:** SVG output always appends `-N` page suffix → `<basename>-1.svg`.
MIDI output → `<basename>.midi` (no suffix). With `page-count = 1` we always get one SVG file.

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
| `lily/midi-walker.cc` | Grace note delta-tick clamping (`output_event` clamps negative delta to 0 → tick-0 collision) |
| `input/regression/point-and-click-types.ly` | `\pointAndClickTypes #'note-event` usage example |

---

## Metronome click track (planned, not implemented)

Opt-in `metronome=False` param on `generate_mp4`. Synthesizes a WAV click track in Python and mixes it into the audio via ffmpeg. No new dependencies.

**Beat positions:** parse timing MIDI (`ticks_per_beat`, tempo map) → enumerate beat ticks → convert to ms list. One beat every `ticks_per_beat` ticks.

**Time signature:** read `time_signature` meta message from MIDI track 0 → numerator = beats per measure. Default 4/4 if absent.

**Click synthesis (`render_click_wav`):**
```python
import wave, struct, math

CLICK_SAMPLE_RATE = 44100
CLICK_DURATION_S  = 0.02   # 20 ms burst
CLICK_FREQ_HZ     = 1000   # beat 2/3/4
ACCENT_FREQ_HZ    = 1500   # beat 1 (louder, higher)
CLICK_AMPLITUDE   = 0.4    # 0..1, accent uses 0.6

def render_click_wav(beat_ms_list, accented_indices, out_path):
    n_samples_total = int((beat_ms_list[-1] / 1000.0 + 1.0) * CLICK_SAMPLE_RATE)
    buf = [0.0] * n_samples_total
    for i, ms in enumerate(beat_ms_list):
        freq = ACCENT_FREQ_HZ if i in accented_indices else CLICK_FREQ_HZ
        amp  = 0.6           if i in accented_indices else CLICK_AMPLITUDE
        start = int(ms / 1000.0 * CLICK_SAMPLE_RATE)
        n_click = int(CLICK_DURATION_S * CLICK_SAMPLE_RATE)
        for k in range(n_click):
            # half-sine envelope to avoid clicks
            env = math.sin(math.pi * k / n_click)
            buf[start + k] += amp * env * math.sin(2 * math.pi * freq * k / CLICK_SAMPLE_RATE)
    with wave.open(str(out_path), 'w') as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(CLICK_SAMPLE_RATE)
        wf.writeframes(b''.join(struct.pack('<h', max(-32768, min(32767, int(s * 32767)))) for s in buf))
```

**Mix:** ffmpeg `-filter_complex "[0:a][1:a]amix=inputs=2:duration=first:weights=1 1"` mixes click WAV with instrument WAV before muxing into MP4. Click WAV path passed as second `-i` to existing ffmpeg mux call.

**Scope of changes:**
- `lyplex_tool.py`: add `render_click_wav(timing_midi_path, out_wav)` function; add `metronome: bool = False` to `generate_mp4`; update ffmpeg mux command to accept optional second audio input
- `lyplex_gui.py`: one `CheckBox` "Add metronome click" in settings grid

**Decision:** Option A (Python PCM synthesis) chosen over Option B (click MIDI → fluidsynth) because click quality is consistent regardless of SF2 content; no extra fluidsynth call; accent on beat 1 is trivial.

---

## Design decisions (resolved)

- **No `\version` in `.ly`:** abort with clear error — LilyPond always declares version; missing = broken file.
- **No SF2 / fluidsynth:** hard error before pipeline starts.
- **SVG/MIDI beat group mismatch (svg > midi):** reconcile by merging closest consecutive SVG pairs
  (grace-note tick-0 collision path in `lily/midi-walker.cc`). Keep rightmost x after merge.
- **SVG/MIDI beat group mismatch (svg < midi):** warn, ignore extra MIDI events.
- **Multi-staff timing map:** staff with longest total note duration drives the timing map.

---

## Implementation status

| File | Status |
|------|--------|
| `lyplex_tool.py` | Done — full pipeline, cursor line + trail overlay, bar-level timing, CLI entry point |
| `lyplex_gui.py` | Done — wxPython GUI, cursor/trail checkboxes, background thread, CR log |
| `lyplex_web.py` | Not started (low priority) |

**Overlay features (opt-in, both default off):**
- `cursor_line=True` — 2px red vertical line at 45% viewport width each frame
- `trail=True` — semi-transparent blue tint over played region + fading red dots at past TRAIL_DOTS notehead positions; dots use bisect for O(log n) per-frame lookup; tint overlay pre-built outside loop

---

## defineScrollingTask — bar-based timing map (IMPLEMENTED)

### Problem with current anchor-based approach

`_select_dominant_staff_anchors` picks the SVG y-cluster closest in group count
to the MIDI driving track (longest total duration). Works for chord names + melody.
Open edge case: a staff with 32nd-note runs → MIDI picks it (most total duration) →
SVG also picks it → scroll twitches on every 32nd note.

### Solution implemented: Option C (hybrid snap)

**Option B (`\pointAndClickTypes #'bar-event`) is not viable.**
`lily/bar-engraver.cc` line 530: `bar_ = make_item("BarLine", SCM_EOL)` — BarLine grob
created with no event cause. `grob-cause` in `scm/output-svg.scm` checks
`(ly:grob-property grob 'cause)` → always empty for BarLine → no anchor ever emitted.

**Option C (hybrid snap) is implemented.**

Pipeline:
1. Build note-level timing_map as before (existing `build_timing_map`)
2. Parse `time_signature` meta from timing MIDI → `(numerator, denominator)`
3. Compute bar start ticks: `0, ticks_per_bar, 2×ticks_per_bar, ...`  
   where `ticks_per_bar = ticks_per_beat × numerator × 4 / denominator`
4. For each bar tick → ms via `_tick_to_ms`; x,y via linear interpolation from note-level map
5. Result: bar-level `timing_map` with one entry per bar

Functions added:
- `_parse_time_signature(midi_file) → (int, int)` — reads first `time_signature` meta
- `_interp_timing_map(ms, timing_map, ms_keys) → (x, y)` — linear interp at arbitrary ms
- `build_bar_timing_map(note_timing_map, tempo_map, ticks_per_beat, time_sig) → list[TimingEntry]`

`extract_timing_midi` now returns 4-tuple: `(note_ons, tempo_map, ticks_per_beat, time_sig)`.

`generate_mp4` has new param `use_bar_timing: bool = True` (default on).
CLI: `--no-bar-timing` flag to revert to note-level.

### Known limitation

Bar x-positions are interpolated from note anchors — no true SVG bar-line geometry used.
This works well when notes are dense (interpolation is close to actual bar line x).
For bars with only long notes (whole notes, multi-measure rests), x interpolation is still correct
because the note anchor at bar start maps exactly to bar start tick.

---

## Known gaps / TODO

- [x] Grace notes: tick-0 collision handled by merging closest SVG pairs when svg_count > midi_count
- [x] Strip PNG memory: warns if estimated RAM > 400 MB; tiling deferred for very long scores
- [x] Scroll clamp: before first note → offset=0; after last note → hold last position (implemented in scroll_offset_at)
- [x] `~` stripping: `re.sub(r'~', '', source)` — safe, `~` is exclusively ties in practice
- [ ] `cluster-note-event` excluded by `\pointAndClickTypes #'note-event` — clusters get no anchor (rare, deferred)
- [x] Multi-staff (piano): noteheads at same beat share same x across staves — no special handling needed
- [ ] Multi-page LilyPond output (paginated scroll) — harder than single strip; deferred
- [x] Font embedding in cairosvg: falls back gracefully through Arial → DejaVu → Pillow default; logs warning when default used
- [x] Lyrics / annotations in SVG: included automatically by LilyPond, no extra work
- [x] Dynamics / hairpins: rendered by LilyPond, visible in SVG, no special handling
- [x] SVG/MIDI mismatch (svg>midi): reconciled via closest-pair SVG merge (grace note case)
- [x] SVG/MIDI mismatch (svg<midi): truncation is correct — can only animate to anchors that exist in SVG; extra MIDI events are for notes without visual anchors
- [x] Metronome click track: mix synthesized clicks into audio at beat onsets

---

## Pending refactors

All done. No pending refactors.
