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
from dataclasses import dataclass, replace as dc_replace
from pathlib import Path
from typing import Optional

import mido
from lxml import etree
from PIL import Image, ImageDraw, ImageFont
import cairosvg

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

XLINK = "http://www.w3.org/1999/xlink"
SVG_NS = "http://www.w3.org/2000/svg"
CURSOR_POSITION = 0.45   # cursor at 45% from left edge
TRAIL_DOTS = 10          # number of past beat positions shown as fading dots
TRAIL_DOT_RADIUS = 5     # dot radius in pixels
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
    y: float = 0.0  # SVG viewBox units (mean of beat group anchors)

@dataclass
class AnchorInfo:
    x: float   # absolute SVG units
    y: float   # absolute SVG units
    line: int
    col: int

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

def _require_binary(name: str, override: str | None = None) -> str:
    if override:
        p = Path(override)
        if not p.is_file():
            raise RuntimeError(f"Binary not found at specified path: {override}")
        return str(p)
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

def _strip_book_output_name(source: str) -> str:
    # Remove \bookOutputName "..." so LilyPond uses our patched filename, not the original.
    return re.sub(r'\\bookOutputName\s+"[^"]*"', "", source)

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
  paper-width = 5000\mm
  line-width = 4990\mm
  paper-height = 250\mm
  top-margin = 5\mm
  bottom-margin = 5\mm
  indent = 0
}
"""
    return source + paper

def patch_ly_svg(source: str) -> str:
    s = _strip_book_output_name(source)
    s = _strip_ties(s)
    s = _inject_point_and_click_types(s)
    s = _add_strip_paper(s)
    return s

def patch_ly_timing_midi(source: str) -> str:
    s = _strip_book_output_name(source)
    s = _strip_ties(s)
    s = _strip_unfold_repeats(s)
    s = _add_strip_paper(s)
    return s

def patch_ly_audio_midi(source: str) -> str:
    s = _strip_book_output_name(source)
    return _add_strip_paper(s)

def _has_unfold_repeats(source: str) -> bool:
    return bool(re.search(r"\\unfoldRepeats\b", source))

# ---------------------------------------------------------------------------
# Header extraction
# ---------------------------------------------------------------------------

def _extract_header(source: str) -> dict[str, str]:
    """Parse \\header block for title, subtitle, composer, copyright, tagline."""
    m = re.search(r'\\header\s*\{([^}]*)\}', source, re.DOTALL)
    if not m:
        return {}
    block = m.group(1)
    result: dict[str, str] = {}
    for key in ('title', 'subtitle', 'composer', 'copyright', 'tagline'):
        km = re.search(rf'{key}\s*=\s*"([^"]*)"', block)
        if km:
            result[key] = km.group(1)
    return result

# ---------------------------------------------------------------------------
# Font helper
# ---------------------------------------------------------------------------

def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ):
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                pass
    return ImageFont.load_default(size=size)

# ---------------------------------------------------------------------------
# Title / footer fixed overlay
# ---------------------------------------------------------------------------

def build_title_footer_overlay(
    width: int,
    height: int,
    header: dict[str, str],
    show_title: bool,
    show_footer: bool,
) -> Image.Image | None:
    """Return a fixed RGBA overlay image with title band (top) and/or footer band (bottom).
    Returns None if nothing to draw."""
    title_lines: list[tuple[str, str]] = []  # (kind, text)
    footer_text = ""

    if show_title:
        if header.get('title'):
            title_lines.append(('title', header['title']))
        if header.get('subtitle'):
            title_lines.append(('subtitle', header['subtitle']))
        if header.get('composer'):
            title_lines.append(('composer', header['composer']))

    if show_footer:
        footer_text = header.get('copyright') or header.get('tagline') or ""

    if not title_lines and not footer_text:
        return None

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    pad = max(6, height // 120)

    if title_lines:
        fonts = {
            'title':    _get_font(max(16, height // 28)),
            'subtitle': _get_font(max(12, height // 40)),
            'composer': _get_font(max(12, height // 40)),
        }
        line_heights = [draw.textbbox((0, 0), text, font=fonts[kind])[3] for kind, text in title_lines]
        band_h = sum(line_heights) + pad * (len(title_lines) + 1)
        draw.rectangle([(0, 0), (width - 1, band_h)], fill=(0, 0, 0, 150))
        y = pad
        for kind, text in title_lines:
            font = fonts[kind]
            bb = draw.textbbox((0, 0), text, font=font)
            tw = bb[2] - bb[0]
            x = width - tw - pad * 2 if kind == 'composer' else (width - tw) // 2
            draw.text((x, y), text, font=font, fill=(255, 255, 255, 230))
            y += (bb[3] - bb[1]) + pad // 2

    if footer_text:
        font = _get_font(max(10, height // 52))
        bb = draw.textbbox((0, 0), footer_text, font=font)
        tw = bb[2] - bb[0]
        th = bb[3] - bb[1]
        band_h = th + pad * 2
        draw.rectangle([(0, height - band_h), (width - 1, height - 1)], fill=(0, 0, 0, 150))
        draw.text(((width - tw) // 2, height - band_h + pad), footer_text,
                  font=font, fill=(255, 255, 255, 200))

    return overlay

# ---------------------------------------------------------------------------
# LilyPond compile
# ---------------------------------------------------------------------------

def _compile_lilypond(patched_source: str, basename: str, workdir: str, lilypond_exe: str | None = None) -> None:
    ly_file = Path(workdir) / f"{basename}.ly"
    ly_file.write_text(patched_source, encoding="utf-8")

    lilypond = _require_binary("lilypond", lilypond_exe)
    cmd = [lilypond, "--svg", "-dpoint-and-click", str(ly_file)]
    result = subprocess.run(
        cmd,
        cwd=workdir,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        print(result.stdout.rstrip())
    if result.stderr.strip():
        print(result.stderr.rstrip())
    if result.returncode != 0:
        raise RuntimeError(
            f"LilyPond compilation failed (exit {result.returncode})"
        )

def compile_svg(source: str, workdir: str, lilypond_exe: str | None = None) -> Path:
    patched = patch_ly_svg(source)
    _compile_lilypond(patched, "score-svg", workdir, lilypond_exe)
    # LilyPond names output after the .ly basename, but \bookOutputName can override it.
    # Glob for any SVG produced (exclude the patched source file itself).
    svgs = [f for f in sorted(Path(workdir).glob("*.svg")) if f.stem != "score-svg"]
    if not svgs:
        # fallback: maybe it IS named score-svg
        svgs = list(Path(workdir).glob("*.svg"))
    if svgs:
        if len(svgs) > 1:
            print(f"[lyplex] WARNING: multiple SVGs found, using {svgs[0].name}")
        return svgs[0]
    files = sorted(Path(workdir).iterdir())
    listing = "\n  ".join(f.name for f in files) or "(empty)"
    raise RuntimeError(
        f"LilyPond did not produce SVG.\nWorkdir contents:\n  {listing}"
    )

def compile_timing_midi(source: str, workdir: str, lilypond_exe: str | None = None) -> Path:
    patched = patch_ly_timing_midi(source)
    _compile_lilypond(patched, "score-timing", workdir, lilypond_exe)
    midi_path = Path(workdir) / "score-timing.midi"
    if not midi_path.exists():
        midi_path = Path(workdir) / "score-timing.mid"
    if not midi_path.exists():
        raise RuntimeError("LilyPond did not produce timing MIDI.")
    return midi_path

def compile_audio_midi(source: str, workdir: str, lilypond_exe: str | None = None) -> Path:
    patched = patch_ly_audio_midi(source)
    _compile_lilypond(patched, "score-audio", workdir, lilypond_exe)
    midi_path = Path(workdir) / "score-audio.midi"
    if not midi_path.exists():
        midi_path = Path(workdir) / "score-audio.mid"
    if not midi_path.exists():
        raise RuntimeError("LilyPond did not produce audio MIDI.")
    return midi_path

# ---------------------------------------------------------------------------
# SVG parsing — anchor extraction
# ---------------------------------------------------------------------------

def _accumulate_translate(element) -> tuple[float, float]:
    """Walk ancestor chain, sum all translate(x,y) values."""
    x_total = 0.0
    y_total = 0.0
    node = element
    while node is not None:
        transform = node.get("transform", "")
        for m in re.finditer(r"translate\(\s*([+-]?\d*\.?\d+)\s*(?:,\s*([+-]?\d*\.?\d+)\s*)?\)", transform):
            x_total += float(m.group(1))
            y_total += float(m.group(2)) if m.group(2) is not None else 0.0
        node = node.getparent()
    return x_total, y_total

def _first_child_translate(element) -> tuple[float, float]:
    """LilyPond 2.24: <a> directly contains <g transform="translate(x,y)">.
    Return translate of first child <g>; fall back to ancestor walk."""
    for child in element:
        transform = child.get("transform", "")
        m = re.search(r"translate\(\s*([+-]?\d*\.?\d+)\s*(?:,\s*([+-]?\d*\.?\d+)\s*)?\)", transform)
        if m:
            return float(m.group(1)), float(m.group(2)) if m.group(2) else 0.0
    return _accumulate_translate(element)

def _extract_anchors_from_root(root) -> list[AnchorInfo]:
    anchors: list[AnchorInfo] = []
    a_elements = list(root.iter(f"{{{SVG_NS}}}a")) or list(root.iter("a"))
    print(f"[lyplex] SVG <a> elements found: {len(a_elements)}")
    for a in a_elements:
        href = (a.get(f"{{{XLINK}}}href", "")
                or a.get("href", "")
                or a.get("xlink:href", ""))
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
        x, y = _first_child_translate(a)
        anchors.append(AnchorInfo(x=x, y=y, line=line, col=col))
    anchors.sort(key=lambda a: a.x)
    return anchors

def extract_svg_anchors(svg_path: Path) -> list[AnchorInfo]:
    return _extract_anchors_from_root(etree.parse(str(svg_path)).getroot())

# ---------------------------------------------------------------------------
# SVG coordinate conversion
# ---------------------------------------------------------------------------

def _parse_mm(value: str) -> float:
    return float(value.removesuffix("mm"))

def _svg_scale_from_root(root, output_height: int) -> tuple[float, float]:
    """Returns (render_dpi, px_per_svgu)."""
    svg_width_mm = _parse_mm(root.get("width", "0mm"))
    svg_height_mm = _parse_mm(root.get("height", "0mm"))
    vb = root.get("viewBox", "0 0 1 1").split()
    viewbox_width = float(vb[2])
    render_dpi = (output_height / svg_height_mm) * 25.4
    px_per_mm = render_dpi / 25.4
    px_per_svgu = svg_width_mm * px_per_mm / viewbox_width
    return render_dpi, px_per_svgu

def svg_px_scale(svg_path: Path, output_height: int) -> tuple[float, float]:
    """Returns (render_dpi, px_per_svgu)."""
    return _svg_scale_from_root(etree.parse(str(svg_path)).getroot(), output_height)

# ---------------------------------------------------------------------------
# MIDI parsing
# ---------------------------------------------------------------------------

def _build_tempo_map(midi_file: mido.MidiFile) -> list[tuple[int, float, int]]:
    """Returns [(tick, ms, tempo_us), ...] checkpoints; tempo_us active from that tick onward."""
    tempo = 500000
    checkpoints: list[tuple[int, float, int]] = [(0, 0.0, tempo)]
    elapsed_ticks = 0
    elapsed_ms = 0.0

    for msg in mido.merge_tracks(midi_file.tracks):
        elapsed_ms += mido.tick2second(msg.time, midi_file.ticks_per_beat, tempo) * 1000
        elapsed_ticks += msg.time
        if msg.type == "set_tempo":
            tempo = msg.tempo
            checkpoints.append((elapsed_ticks, elapsed_ms, tempo))

    return checkpoints

def _tick_to_ms(tick: int, tempo_map: list[tuple[int, float, int]], ticks_per_beat: int) -> float:
    if not tempo_map:
        return 0.0
    base_tick, base_ms, tempo_us = tempo_map[0]
    for cp_tick, cp_ms, cp_tempo in tempo_map:
        if cp_tick > tick:
            break
        base_tick, base_ms, tempo_us = cp_tick, cp_ms, cp_tempo
    return base_ms + mido.tick2second(tick - base_tick, ticks_per_beat, tempo_us) * 1000

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

def extract_timing_midi(midi_path: Path) -> tuple[list[tuple[int, int]], list[tuple[int, float, int]], int]:
    """
    Returns (note_ons, tempo_map, ticks_per_beat).
    note_ons: [(tick, pitch), ...] from the staff with longest total duration.
    tempo_map: [(tick, ms, tempo_us), ...] checkpoints.
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

def _select_dominant_staff_anchors(anchors: list[AnchorInfo], y_gap: float = 1.5) -> list[AnchorInfo]:
    """When multiple staves exist, keep only the one with fewest beat groups (longest note values).

    Clusters anchors by y, splitting on gaps > y_gap SVG units.  Picks the
    cluster with the fewest unique x positions — i.e. the staff whose notes
    last the longest on average (chord names, bass line, etc.).  Falls back
    to all anchors when only one cluster is found.
    """
    if not anchors:
        return anchors

    sorted_ys = sorted(set(round(a.y, 1) for a in anchors))
    clusters: list[tuple[float, float]] = []
    lo = hi = sorted_ys[0]
    for y in sorted_ys[1:]:
        if y - hi > y_gap:
            clusters.append((lo, hi))
            lo = hi = y
        else:
            hi = y
    clusters.append((lo, hi))

    if len(clusters) <= 1:
        return anchors

    best_cluster, best_count = None, float("inf")
    for c_lo, c_hi in clusters:
        ca = [a for a in anchors if c_lo - 0.05 <= round(a.y, 1) <= c_hi + 0.05]
        x_count = len(set(round(a.x, 2) for a in ca))
        if x_count < best_count:
            best_count = x_count
            best_cluster = (c_lo, c_hi, ca)

    c_lo, c_hi, selected = best_cluster
    print(f"[lyplex] {len(clusters)} staves detected; using y=[{c_lo},{c_hi}] "
          f"({len(selected)} anchors, {best_count} beat groups, longest note values)")
    return selected

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
    anchors = _select_dominant_staff_anchors(anchors)
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
        max_anchor = max(svg_groups[i], key=lambda a: a.x)
        x = max_anchor.x  # rightmost anchor = main note position
        y = max_anchor.y  # y of the same anchor (avoids blank-space mean across staves)
        tick = midi_groups[i][0][0]
        ms = _tick_to_ms(tick, tempo_map, ticks_per_beat)
        timing_map.append(TimingEntry(ms=ms, x=x, y=y))

    return timing_map

# ---------------------------------------------------------------------------
# Scroll interpolation
# ---------------------------------------------------------------------------

def scroll_offset_at(
    ms: float,
    timing_map: list[TimingEntry],
    viewport_width: int,
    ms_keys: list[float] | None = None,
) -> float:
    if not timing_map:
        return 0.0
    if ms <= timing_map[0].ms:
        return 0.0
    if ms >= timing_map[-1].ms:
        score_x = timing_map[-1].x
        return max(0.0, score_x - viewport_width * CURSOR_POSITION)

    keys = ms_keys if ms_keys is not None else [e.ms for e in timing_map]
    i = bisect_left(keys, ms) - 1
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

def render_audio_wav(midi_path: Path, sf2_path: str, wav_path: Path, fluidsynth_exe: str | None = None) -> None:
    fs = _require_binary("fluidsynth", fluidsynth_exe)
    cmd = [
        fs,
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
    ffmpeg_exe: str | None = None,
    cursor_line: bool = False,
    trail: bool = False,
    title_footer_overlay: Image.Image | None = None,
) -> None:
    ffmpeg = _require_binary("ffmpeg", ffmpeg_exe)

    # Duration = last note ms + 2s tail
    duration_ms = timing_map[-1].ms + 2000.0
    n_frames = int(duration_ms / 1000.0 * fps) + 1

    audio_filters = _atempo_filter(atempo) if abs(atempo - 1.0) > 1e-6 else None

    ffmpeg_cmd = [
        ffmpeg, "-y",
        "-framerate", str(fps),
        "-f", "image2pipe",
        "-vcodec", "ppm",
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

    ms_keys = [e.ms for e in timing_map]
    cx = int(width * CURSOR_POSITION)
    # Pre-build the loop-invariant tint overlay (region left of cursor, semi-transparent blue)
    if trail:
        _tint_base = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        ImageDraw.Draw(_tint_base).rectangle([(0, 0), (cx - 1, height - 1)], fill=(100, 140, 220, 35))
    try:
        for frame_n in range(n_frames):
            t_ms = frame_n / fps * 1000.0
            offset_svgu = scroll_offset_at(t_ms, timing_map, width, ms_keys)
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

            if trail or cursor_line:
                if trail:
                    overlay = _tint_base.copy()
                    ov = ImageDraw.Draw(overlay)

                    # Dots: last TRAIL_DOTS past beat positions — bisect avoids O(n) scan
                    i_trail = bisect_left(ms_keys, t_ms)
                    past = timing_map[max(0, i_trail - TRAIL_DOTS):i_trail]
                    n_past = len(past)
                    for idx, entry in enumerate(past):
                        ex_px = int(entry.x * px_per_svgu) - left
                        ey_px = int(entry.y * px_per_svgu)
                        if -TRAIL_DOT_RADIUS <= ex_px <= width + TRAIL_DOT_RADIUS:
                            alpha = int(200 * (idx + 1) / n_past) if n_past else 0
                            r = TRAIL_DOT_RADIUS
                            ov.ellipse(
                                [(ex_px - r, ey_px - r), (ex_px + r, ey_px + r)],
                                fill=(220, 80, 50, alpha),
                            )

                    frame = Image.alpha_composite(frame.convert("RGBA"), overlay).convert("RGB")

                if cursor_line:
                    draw = ImageDraw.Draw(frame)
                    draw.line([(cx, 0), (cx, height - 1)], fill=(220, 50, 50), width=2)

            if title_footer_overlay is not None:
                frame = Image.alpha_composite(frame.convert("RGBA"), title_footer_overlay).convert("RGB")

            frame.save(proc.stdin, format="PPM")

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
    lilypond_exe: str | None = None,
    ffmpeg_exe: str | None = None,
    fluidsynth_exe: str | None = None,
    cursor_line: bool = False,
    trail: bool = False,
    overlay_title: bool = False,
    overlay_footer: bool = False,
) -> None:
    # Preflight
    _require_binary("lilypond", lilypond_exe)
    _require_binary("ffmpeg", ffmpeg_exe)
    _require_binary("fluidsynth", fluidsynth_exe)
    _require_soundfont(sf2_path)

    source = Path(ly_path).read_text(encoding="utf-8")
    _require_version_declaration(source, ly_path)

    header = _extract_header(source)
    needs_audio_midi = _has_unfold_repeats(source)

    workdir = tempfile.mkdtemp(prefix="lyplex_")
    try:
        print(f"[lyplex] workdir: {workdir}")

        # Compile
        print("[lyplex] compiling SVG...")
        svg_path = compile_svg(source, workdir, lilypond_exe)

        print("[lyplex] compiling timing MIDI...")
        timing_midi_path = compile_timing_midi(source, workdir, lilypond_exe)

        if needs_audio_midi:
            print("[lyplex] compiling audio MIDI (has \\unfoldRepeats)...")
            audio_midi_path = compile_audio_midi(source, workdir, lilypond_exe)
        else:
            audio_midi_path = timing_midi_path

        # Parse SVG once — shared between anchor extraction and scale computation
        svg_root = etree.parse(str(svg_path)).getroot()

        print("[lyplex] extracting SVG anchors...")
        anchors = _extract_anchors_from_root(svg_root)
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
            timing_map = [dc_replace(e, ms=e.ms / tempo_multiplier) for e in timing_map]

        # Scale
        render_dpi, px_per_svgu = _svg_scale_from_root(svg_root, height)

        # Render strip
        strip_png = Path(workdir) / "strip.png"
        print(f"[lyplex] rendering strip PNG at {render_dpi:.1f} dpi...")
        render_strip_png(svg_path, render_dpi, strip_png)
        strip_img = Image.open(str(strip_png)).convert("RGB")

        # Audio
        wav_path = Path(workdir) / "audio.wav"
        print("[lyplex] rendering audio...")
        render_audio_wav(audio_midi_path, sf2_path, wav_path, fluidsynth_exe)

        # Build fixed title/footer overlay (done once, composited every frame)
        tf_overlay = build_title_footer_overlay(width, height, header, overlay_title, overlay_footer)

        # Encode
        print("[lyplex] encoding MP4...")
        encode_mp4(
            strip_img, timing_map, px_per_svgu,
            wav_path, Path(out_path),
            width=width, height=height, fps=fps,
            atempo=tempo_multiplier,
            ffmpeg_exe=ffmpeg_exe,
            cursor_line=cursor_line,
            trail=trail,
            title_footer_overlay=tf_overlay,
        )

        print(f"[lyplex] done: {out_path}")

    finally:
        import sys
        if sys.exc_info()[0] is None:
            shutil.rmtree(workdir, ignore_errors=True)
        else:
            print(f"[lyplex] workdir preserved for inspection (error): {workdir}")


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
