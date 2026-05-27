"""
lyplex_tool.py — core pipeline: LilyPond → SVG/MIDI → timing map → MP4
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import warnings
from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import mido
from lxml import etree
from PIL import Image
import cairosvg

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

XLINK = "http://www.w3.org/1999/xlink"
SVG_NS = "http://www.w3.org/2000/svg"
CURSOR_POSITION = 0.45   # cursor at 45% from left edge
DEFAULT_FPS = 30
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class TimingEntry:
    ms: float
    x: float  # SVG viewBox units

@dataclass
class AnchorInfo:
    x: float   # absolute SVG units
    line: int
    col: int

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"Required binary not found on PATH: {name}")
    return path

def _require_version_declaration(source: str, ly_path: str) -> None:
    if not re.search(r'\\version\s+"[^"]*"', source):
        raise ValueError(
            f"No \\version declaration found in {ly_path}. "
            "LilyPond files must declare a version. Aborting."
        )

def _require_soundfont(sf2_path: str) -> None:
    if not sf2_path or not Path(sf2_path).is_file():
        raise FileNotFoundError(
            f"Soundfont not found: {sf2_path!r}. "
            "A valid .sf2 file is required for audio rendering."
        )

# ---------------------------------------------------------------------------
# .ly patching
# ---------------------------------------------------------------------------

def _strip_ties(source: str) -> str:
    return re.sub(r"~", "", source)

def _strip_unfold_repeats(source: str) -> str:
    return re.sub(r"\\unfoldRepeats\b", "", source)

def _inject_point_and_click_types(source: str) -> str:
    """Insert \pointAndClickTypes #'note-event after the \version line."""
    def replacer(m):
        return m.group(0) + "\n\\pointAndClickTypes #'note-event"
    result, n = re.subn(r'(\\version\s+"[^"]*")', replacer, source, count=1)
    if n == 0:
        raise ValueError("Could not inject \\pointAndClickTypes: no \\version line found.")
    return result

def _add_strip_paper(source: str) -> str:
    """Append single-strip paper block."""
    paper = r"""
\paper {
  line-width = 9999\mm
  page-count = 1
  indent = 0
}
"""
    return source + paper

def patch_ly_svg(source: str) -> str:
    s = _strip_ties(source)
    s = _inject_point_and_click_types(s)
    s = _add_strip_paper(s)
    return s

def patch_ly_timing_midi(source: str) -> str:
    s = _strip_ties(source)
    s = _strip_unfold_repeats(s)
    s = _add_strip_paper(s)
    return s

def patch_ly_audio_midi(source: str) -> str:
    # original source — only add strip paper
    return _add_strip_paper(source)

def _has_unfold_repeats(source: str) -> bool:
    return bool(re.search(r"\\unfoldRepeats\b", source))

# ---------------------------------------------------------------------------
# LilyPond compile
# ---------------------------------------------------------------------------

def _compile_lilypond(patched_source: str, basename: str, workdir: str) -> None:
    ly_file = Path(workdir) / f"{basename}.ly"
    ly_file.write_text(patched_source, encoding="utf-8")

    lilypond = _require_binary("lilypond")
    cmd = [lilypond, "-dsvg", "-dpoint-and-click", str(ly_file)]
    result = subprocess.run(
        cmd,
        cwd=workdir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"LilyPond compilation failed:\n{result.stderr}"
        )

def compile_svg(source: str, workdir: str) -> Path:
    patched = patch_ly_svg(source)
    _compile_lilypond(patched, "score-svg", workdir)
    svg_path = Path(workdir) / "score-svg.svg"
    if not svg_path.exists():
        raise RuntimeError(f"LilyPond did not produce {svg_path}")
    return svg_path

def compile_timing_midi(source: str, workdir: str) -> Path:
    patched = patch_ly_timing_midi(source)
    _compile_lilypond(patched, "score-timing", workdir)
    midi_path = Path(workdir) / "score-timing.midi"
    if not midi_path.exists():
        midi_path = Path(workdir) / "score-timing.mid"
    if not midi_path.exists():
        raise RuntimeError("LilyPond did not produce timing MIDI.")
    return midi_path

def compile_audio_midi(source: str, workdir: str) -> Path:
    patched = patch_ly_audio_midi(source)
    _compile_lilypond(patched, "score-audio", workdir)
    midi_path = Path(workdir) / "score-audio.midi"
    if not midi_path.exists():
        midi_path = Path(workdir) / "score-audio.mid"
    if not midi_path.exists():
        raise RuntimeError("LilyPond did not produce audio MIDI.")
    return midi_path

# ---------------------------------------------------------------------------
# SVG parsing — anchor extraction
# ---------------------------------------------------------------------------

def _accumulate_translate_x(element) -> float:
    """Walk ancestor chain, sum all translate(x,y) x-values."""
    x_total = 0.0
    node = element
    while node is not None:
        transform = node.get("transform", "")
        for m in re.finditer(r"translate\(\s*([+-]?\d*\.?\d+)\s*(?:,\s*([+-]?\d*\.?\d+)\s*)?\)", transform):
            x_total += float(m.group(1))
        node = node.getparent()
    return x_total

def extract_svg_anchors(svg_path: Path) -> list[AnchorInfo]:
    tree = etree.parse(str(svg_path))
    root = tree.getroot()

    anchors: list[AnchorInfo] = []

    for a in root.iter(f"{{{SVG_NS}}}a"):
        href = a.get(f"{{{XLINK}}}href", "")
        if not href.startswith("textedit://"):
            continue
        # textedit://FILE:LINE:CHR:COL
        parts = href[len("textedit://"):].rsplit(":", 3)
        if len(parts) != 4:
            continue
        try:
            line = int(parts[1])
            col = int(parts[2])
        except ValueError:
            continue

        x = _accumulate_translate_x(a)
        anchors.append(AnchorInfo(x=x, line=line, col=col))

    anchors.sort(key=lambda a: a.x)
    return anchors

# ---------------------------------------------------------------------------
# SVG coordinate conversion
# ---------------------------------------------------------------------------

def _parse_mm(value: str) -> float:
    return float(value.rstrip("m").rstrip("m"))

def svg_px_scale(svg_path: Path, output_height: int) -> tuple[float, float]:
    """Returns (render_dpi, px_per_svgu)."""
    tree = etree.parse(str(svg_path))
    root = tree.getroot()

    svg_width_mm = _parse_mm(root.get("width", "0mm"))
    svg_height_mm = _parse_mm(root.get("height", "0mm"))
    vb = root.get("viewBox", "0 0 1 1").split()
    viewbox_width = float(vb[2])

    render_dpi = (output_height / svg_height_mm) * 25.4
    px_per_mm = render_dpi / 25.4
    px_per_svgu = svg_width_mm * px_per_mm / viewbox_width

    return render_dpi, px_per_svgu

# ---------------------------------------------------------------------------
# MIDI parsing
# ---------------------------------------------------------------------------

def _build_tempo_map(midi_file: mido.MidiFile) -> list[tuple[int, float]]:
    """Returns [(tick, ms), ...] checkpoints."""
    tempo = 500000
    checkpoints: list[tuple[int, float]] = [(0, 0.0)]
    elapsed_ticks = 0
    elapsed_ms = 0.0

    for msg in mido.merge_tracks(midi_file.tracks):
        elapsed_ticks += msg.time
        if msg.type == "set_tempo":
            elapsed_ms += mido.tick2second(msg.time, midi_file.ticks_per_beat, tempo) * 1000
            tempo = msg.tempo
            checkpoints.append((elapsed_ticks, elapsed_ms))

    return checkpoints

def _tick_to_ms(tick: int, tempo_map: list[tuple[int, float]], ticks_per_beat: int) -> float:
    if not tempo_map:
        return 0.0
    idx = bisect_left(tempo_map, (tick,)) - 1
    idx = max(0, min(idx, len(tempo_map) - 1))
    base_tick, base_ms = tempo_map[idx]

    # find tempo at this segment
    if idx + 1 < len(tempo_map):
        next_tick, next_ms = tempo_map[idx + 1]
        seg_ticks = next_tick - base_tick
        seg_ms = next_ms - base_ms
        tempo_us_per_beat = (seg_ms / seg_ticks * ticks_per_beat * 1000) if seg_ticks else 500000
    else:
        tempo_us_per_beat = 500000

    delta_ticks = tick - base_tick
    delta_ms = mido.tick2second(delta_ticks, ticks_per_beat, int(tempo_us_per_beat)) * 1000
    return base_ms + delta_ms

@dataclass
class TrackNoteEvents:
    track_index: int
    note_ons: list[tuple[int, int]]  # (tick, pitch)
    total_duration_ticks: int

def _parse_midi_tracks(midi_file: mido.MidiFile) -> list[TrackNoteEvents]:
    results: list[TrackNoteEvents] = []

    for i, track in enumerate(midi_file.tracks):
        note_ons: list[tuple[int, int]] = []
        abs_tick = 0
        last_tick = 0
        active: dict[int, int] = {}  # pitch → on_tick
        total_dur = 0

        for msg in track:
            abs_tick += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                note_ons.append((abs_tick, msg.note))
                active[msg.note] = abs_tick
            elif msg.type in ("note_off", "note_on") and msg.velocity == 0:
                if msg.note in active:
                    total_dur += abs_tick - active.pop(msg.note)
            last_tick = abs_tick

        if note_ons:
            results.append(TrackNoteEvents(
                track_index=i,
                note_ons=note_ons,
                total_duration_ticks=total_dur,
            ))

    return results

def extract_timing_midi(midi_path: Path) -> tuple[list[tuple[int, int]], list[tuple[int, float]], int]:
    """
    Returns (note_ons, tempo_map, ticks_per_beat).
    note_ons: [(tick, pitch), ...] from the staff with longest total duration.
    """
    midi_file = mido.MidiFile(str(midi_path))
    tempo_map = _build_tempo_map(midi_file)
    tracks = _parse_midi_tracks(midi_file)

    if not tracks:
        raise RuntimeError("No note events found in timing MIDI.")

    # Staff with longest total duration drives timing map
    driving_track = max(tracks, key=lambda t: t.total_duration_ticks)
    note_ons = sorted(driving_track.note_ons, key=lambda e: e[0])

    return note_ons, tempo_map, midi_file.ticks_per_beat

# ---------------------------------------------------------------------------
# Beat group correlation → timing map
# ---------------------------------------------------------------------------

def _group_by_value(items, key_fn) -> list[list]:
    groups: list[list] = []
    seen: dict = {}
    for item in items:
        k = key_fn(item)
        if k not in seen:
            seen[k] = len(groups)
            groups.append([])
        groups[seen[k]].append(item)
    return groups

def _merge_closest_svg_groups(svg_groups: list[list], target: int) -> list[list]:
    """Merge consecutive SVG groups with the smallest x-gap until count == target.

    Used to reconcile grace-note tick collisions: LilyPond's midi-walker clamps
    negative grace-note deltas to 0, collapsing grace+main into one MIDI beat
    group while SVG still has them as two separate groups.  The smallest x-gap
    between consecutive SVG groups is the best proxy for a grace-to-main pair.
    After merging, the group keeps the rightmost anchor x (main note position).
    """
    groups = [list(g) for g in svg_groups]
    while len(groups) > target:
        if len(groups) < 2:
            break
        # x representative per group = rightmost anchor
        xs = [max(a.x for a in g) for g in groups]
        gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
        idx = min(range(len(gaps)), key=lambda i: gaps[i])
        merged = groups[idx] + groups[idx + 1]
        groups = groups[:idx] + [merged] + groups[idx + 2:]
    return groups


def build_timing_map(
    anchors: list[AnchorInfo],
    note_ons: list[tuple[int, int]],
    tempo_map: list[tuple[int, float]],
    ticks_per_beat: int,
) -> list[TimingEntry]:
    # Group anchors by x (same beat moment)
    svg_groups = _group_by_value(anchors, key_fn=lambda a: round(a.x, 2))
    # Group MIDI note_ons by tick
    midi_groups = _group_by_value(note_ons, key_fn=lambda e: e[0])

    if len(svg_groups) > len(midi_groups):
        # More SVG groups than MIDI groups — likely grace-note tick-0 collisions
        # in LilyPond's MIDI writer (midi-walker.cc clamps negative deltas to 0,
        # merging grace+main into one MIDI beat group).  Reconcile by merging
        # the closest consecutive SVG pairs (grace note sits just left of main).
        warnings.warn(
            f"SVG beat groups ({len(svg_groups)}) > MIDI beat groups ({len(midi_groups)}). "
            f"Merging {len(svg_groups) - len(midi_groups)} closest SVG pair(s) (grace notes)."
        )
        svg_groups = _merge_closest_svg_groups(svg_groups, len(midi_groups))
    elif len(svg_groups) < len(midi_groups):
        warnings.warn(
            f"SVG beat groups ({len(svg_groups)}) < MIDI beat groups ({len(midi_groups)}). "
            "Extra MIDI events ignored."
        )

    n = min(len(svg_groups), len(midi_groups))
    timing_map: list[TimingEntry] = []

    for i in range(n):
        x = max(a.x for a in svg_groups[i])  # rightmost anchor = main note position
        tick = midi_groups[i][0][0]
        ms = _tick_to_ms(tick, tempo_map, ticks_per_beat)
        timing_map.append(TimingEntry(ms=ms, x=x))

    return timing_map

# ---------------------------------------------------------------------------
# Scroll interpolation
# ---------------------------------------------------------------------------

def scroll_offset_at(ms: float, timing_map: list[TimingEntry], viewport_width: int) -> float:
    if not timing_map:
        return 0.0
    if ms <= timing_map[0].ms:
        return 0.0
    if ms >= timing_map[-1].ms:
        score_x = timing_map[-1].x
        return max(0.0, score_x - viewport_width * CURSOR_POSITION)

    i = bisect_left([e.ms for e in timing_map], ms) - 1
    i = max(0, min(i, len(timing_map) - 2))

    t0, x0 = timing_map[i].ms, timing_map[i].x
    t1, x1 = timing_map[i + 1].ms, timing_map[i + 1].x

    progress = (ms - t0) / (t1 - t0) if t1 != t0 else 0.0
    score_x = x0 + (x1 - x0) * progress
    return max(0.0, score_x - viewport_width * CURSOR_POSITION)

# ---------------------------------------------------------------------------
# Strip PNG render
# ---------------------------------------------------------------------------

def render_strip_png(svg_path: Path, render_dpi: float, out_path: Path) -> None:
    cairosvg.svg2png(url=str(svg_path), write_to=str(out_path), dpi=render_dpi)

# ---------------------------------------------------------------------------
# Audio render
# ---------------------------------------------------------------------------

def render_audio_wav(midi_path: Path, sf2_path: str, wav_path: Path) -> None:
    _require_binary("fluidsynth")
    cmd = [
        "fluidsynth",
        "-ni",
        "-F", str(wav_path),
        sf2_path,
        str(midi_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"fluidsynth failed:\n{result.stderr}")

# ---------------------------------------------------------------------------
# MP4 export
# ---------------------------------------------------------------------------

def _atempo_filter(multiplier: float) -> str:
    """Build ffmpeg atempo filter chain for any multiplier in [0.25, 4.0]."""
    filters: list[str] = []
    r = multiplier
    while r > 2.0 + 1e-9:
        filters.append("atempo=2.0")
        r /= 2.0
    while r < 0.5 - 1e-9:
        filters.append("atempo=0.5")
        r /= 0.5
    filters.append(f"atempo={r:.6f}")
    return ",".join(filters)


def encode_mp4(
    strip_img: Image.Image,
    timing_map: list[TimingEntry],
    px_per_svgu: float,
    wav_path: Path,
    out_path: Path,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
    atempo: float = 1.0,
) -> None:
    _require_binary("ffmpeg")

    # Duration = last note ms + 2s tail
    duration_ms = timing_map[-1].ms + 2000.0
    n_frames = int(duration_ms / 1000.0 * fps) + 1

    audio_filters = _atempo_filter(atempo) if abs(atempo - 1.0) > 1e-6 else None

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-f", "image2pipe",
        "-vcodec", "png",
        "-i", "pipe:0",
        "-i", str(wav_path),
        "-c:v", "libx264",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
    ]
    if audio_filters:
        ffmpeg_cmd += ["-filter:a", audio_filters]
    ffmpeg_cmd += ["-shortest", str(out_path)]

    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

    try:
        for frame_n in range(n_frames):
            t_ms = frame_n / fps * 1000.0
            offset_svgu = scroll_offset_at(t_ms, timing_map, width)
            offset_px = int(offset_svgu * px_per_svgu)

            left = offset_px
            right = left + width
            # clamp to strip bounds
            if right > strip_img.width:
                left = max(0, strip_img.width - width)
                right = strip_img.width

            frame = strip_img.crop((left, 0, right, height))
            if frame.width < width:
                # pad right edge with white
                padded = Image.new("RGB", (width, height), (255, 255, 255))
                padded.paste(frame, (0, 0))
                frame = padded

            frame.save(proc.stdin, format="PNG")

    finally:
        proc.stdin.close()
        proc.wait()

    if proc.returncode != 0:
        raise RuntimeError("ffmpeg encoding failed.")

# ---------------------------------------------------------------------------
# Top-level pipeline
# ---------------------------------------------------------------------------

def generate_mp4(
    ly_path: str,
    sf2_path: str,
    out_path: str,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
    tempo_multiplier: float = 1.0,
) -> None:
    # Preflight
    _require_binary("lilypond")
    _require_binary("ffmpeg")
    _require_binary("fluidsynth")
    _require_soundfont(sf2_path)

    source = Path(ly_path).read_text(encoding="utf-8")
    _require_version_declaration(source, ly_path)

    needs_audio_midi = _has_unfold_repeats(source)

    workdir = tempfile.mkdtemp(prefix="lyplex_")
    try:
        print(f"[lyplex] workdir: {workdir}")

        # Compile
        print("[lyplex] compiling SVG...")
        svg_path = compile_svg(source, workdir)

        print("[lyplex] compiling timing MIDI...")
        timing_midi_path = compile_timing_midi(source, workdir)

        if needs_audio_midi:
            print("[lyplex] compiling audio MIDI (has \\unfoldRepeats)...")
            audio_midi_path = compile_audio_midi(source, workdir)
        else:
            audio_midi_path = timing_midi_path

        # Parse
        print("[lyplex] extracting SVG anchors...")
        anchors = extract_svg_anchors(svg_path)
        if not anchors:
            raise RuntimeError("No note anchors found in SVG. Check \\pointAndClickTypes injection.")

        print("[lyplex] parsing timing MIDI...")
        note_ons, tempo_map, ticks_per_beat = extract_timing_midi(timing_midi_path)

        # Timing map
        print("[lyplex] building timing map...")
        timing_map = build_timing_map(anchors, note_ons, tempo_map, ticks_per_beat)
        if not timing_map:
            raise RuntimeError("Timing map is empty after correlation.")

        if abs(tempo_multiplier - 1.0) > 1e-6:
            timing_map = [TimingEntry(ms=e.ms / tempo_multiplier, x=e.x) for e in timing_map]

        # Scale
        render_dpi, px_per_svgu = svg_px_scale(svg_path, height)

        # Render strip
        strip_png = Path(workdir) / "strip.png"
        print(f"[lyplex] rendering strip PNG at {render_dpi:.1f} dpi...")
        render_strip_png(svg_path, render_dpi, strip_png)
        strip_img = Image.open(str(strip_png)).convert("RGB")

        # Audio
        wav_path = Path(workdir) / "audio.wav"
        print("[lyplex] rendering audio...")
        render_audio_wav(audio_midi_path, sf2_path, wav_path)

        # Encode
        print("[lyplex] encoding MP4...")
        encode_mp4(
            strip_img, timing_map, px_per_svgu,
            wav_path, Path(out_path),
            width=width, height=height, fps=fps,
            atempo=tempo_multiplier,
        )

        print(f"[lyplex] done: {out_path}")

    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LyPlex: LilyPond → scrolling MP4")
    parser.add_argument("ly_file", help=".ly input file")
    parser.add_argument("sf2_file", help=".sf2 soundfont")
    parser.add_argument("output", help="output .mp4 path")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    args = parser.parse_args()

    generate_mp4(
        ly_path=args.ly_file,
        sf2_path=args.sf2_file,
        out_path=args.output,
        width=args.width,
        height=args.height,
        fps=args.fps,
    )
