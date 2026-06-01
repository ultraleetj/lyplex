"""
lyplex_tool.py — core pipeline: LilyPond → SVG/MIDI → timing map → MP4
"""

from __future__ import annotations

import array
import io
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
import warnings
from bisect import bisect_left
from dataclasses import dataclass, replace as dc_replace
from pathlib import Path

import mido
from lxml import etree
from PIL import Image, ImageDraw, ImageFont
import cairosvg

# Suppress console popup windows on Windows when spawning subprocesses from a GUI.
_WIN_NO_WINDOW: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if sys.platform == "win32" else {}
)

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
    x: float          # SVG viewBox units
    y: float = 0.0    # SVG viewBox units
    duration_ms: float = 0.0  # how long this note/chord sounds

@dataclass
class AnchorInfo:
    x: float   # absolute SVG units
    y: float   # absolute SVG units
    line: int
    col: int

@dataclass
class ClickParams:
    freq_hz: float  = 1000.0
    waveform: str   = "sine"   # sine | square | triangle | saw
    duration_ms: float = 20.0
    amplitude: float   = 0.4

@dataclass
class WatermarkParams:
    path: str = ""           # empty = no watermark
    position: str = "BR"    # TL | TR | BL | BR
    opacity: float = 0.6
    max_height: int | None = None  # px; None → height // 8

@dataclass
class ClickResult:
    wav_path: Path | None = None
    count_in_ms: float = 0.0

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

def _has_volta_repeats(source: str) -> bool:
    return bool(re.search(r"\\repeat\s+volta\b", source))

def _has_chord_names(source: str) -> bool:
    return bool(re.search(r"\\new\s+ChordNames\b", source))

def _has_unfold_repeats(source: str) -> bool:
    return bool(re.search(r"\\unfoldRepeats\b", source))

def _should_unfold_repeats(source: str) -> bool:
    """True when all score variants should have repeats unfolded.

    Skipped when ChordNames is present: chord parts are typically written
    linearly without matching volta structure, causing blank chord strips
    and audio/visual mismatch when unfolded.
    """
    return (_has_volta_repeats(source) or _has_unfold_repeats(source)) and not _has_chord_names(source)

_SCORE_BLOCK_TERMINATORS = re.compile(r"\\(layout|midi|header|paper)\b")

def _find_closing_brace(source: str, start: int) -> int:
    """Return index one past the closing '}' matching the '{' at source[start]."""
    depth = 1
    i = start + 1
    n = len(source)
    while i < n and depth > 0:
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
        i += 1
    return i

def _wrap_score_body_with_unfold(body: str) -> str:
    """Insert \\unfoldRepeats around music portion of a \\score block body."""
    depth = 0
    i = 0
    while i < len(body):
        c = body[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        elif depth == 0:
            m = _SCORE_BLOCK_TERMINATORS.match(body, i)
            if m:
                music = body[:i].strip()
                rest = body[i:].strip()
                return f'\n  \\unfoldRepeats {{\n  {music}\n  }}\n  {rest}\n'
        i += 1
    return f'\n  \\unfoldRepeats {{\n{body}\n  }}\n'

def _inject_unfold_repeats(source: str) -> str:
    """Wrap music content in each \\score block with \\unfoldRepeats { ... }."""
    result = []
    pos = 0
    for m in re.finditer(r'\\score\s*\{', source):
        result.append(source[pos:m.end()])
        end = _find_closing_brace(source, m.end() - 1)
        body = source[m.end():end - 1]
        result.append(_wrap_score_body_with_unfold(body))
        result.append('}')
        pos = end
    result.append(source[pos:])
    return ''.join(result)

def _strip_book_output_name(source: str) -> str:
    # Remove \bookOutputName "..." so LilyPond uses our patched filename, not the original.
    return re.sub(r'\\bookOutputName\s+"[^"]*"', "", source)

def _inject_point_and_click_types(source: str) -> str:
    """Insert \\pointAndClickTypes after the \\version line.
    Includes cluster-note-event so tone cluster grobs get anchors if LilyPond
    attaches a cause event to them (if not, they're silently omitted — no harm)."""
    def replacer(m):
        return m.group(0) + "\n\\pointAndClickTypes #'(note-event cluster-note-event)"
    result, n = re.subn(r'(\\version\s+"[^"]*")', replacer, source, count=1)
    if n == 0:
        raise ValueError("Could not inject \\pointAndClickTypes: no \\version line found.")
    return result

def _inject_all_bar_numbers(source: str) -> str:
    """Append layout block that shows a bar number above every bar."""
    snippet = r"""
\layout {
  \context {
    \Score
    \override BarNumber.break-visibility = ##(#t #t #t)
    barNumberVisibility = #all-bar-numbers-visible
  }
}
"""
    return source + snippet

def _strip_paper_blocks(source: str) -> str:
    """Remove all top-level \\paper { ... } blocks from source."""
    result = []
    pos = 0
    for m in re.finditer(r'\\paper\s*\{', source):
        result.append(source[pos:m.start()])
        pos = _find_closing_brace(source, m.end() - 1)
    result.append(source[pos:])
    return ''.join(result)


def _add_strip_paper(source: str) -> str:
    """Strip any existing \\paper blocks then append single-strip paper block."""
    source = _strip_paper_blocks(source)
    paper = r"""
\paper {
  system-count = 1
  paper-width = 9999\mm
  line-width = 9989\mm
  paper-height = 250\mm
  top-margin = 5\mm
  bottom-margin = 5\mm
  indent = 0
}
"""
    return source + paper

def patch_ly_svg(source: str, bar_numbers: bool = True) -> str:
    s = _strip_book_output_name(source)
    s = _strip_ties(s)
    if _should_unfold_repeats(source):
        s = _strip_unfold_repeats(s)
        s = _inject_unfold_repeats(s)
    s = _inject_point_and_click_types(s)
    if bar_numbers:
        s = _inject_all_bar_numbers(s)
    s = _add_strip_paper(s)
    return s

def patch_ly_timing_midi(source: str) -> str:
    s = _strip_book_output_name(source)
    s = _strip_ties(s)
    s = _strip_unfold_repeats(s)
    if _should_unfold_repeats(source):
        s = _inject_unfold_repeats(s)
    s = _add_strip_paper(s)
    return s

def patch_ly_audio_midi(source: str) -> str:
    s = _strip_book_output_name(source)
    if _should_unfold_repeats(source):
        s = _strip_unfold_repeats(s)
        s = _inject_unfold_repeats(s)
    return _add_strip_paper(s)

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
    print(f"[lyplex] WARNING: no TrueType font found at size {size}; overlay text will use Pillow bitmap fallback.")
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


def _load_logo(logo_path: str, max_h: int) -> Image.Image | None:
    """Load SVG or raster logo, scale to max_h, convert to RGBA. Returns None on failure."""
    try:
        if Path(logo_path).suffix.lower() == ".svg":
            png_bytes = cairosvg.svg2png(url=logo_path, output_height=max_h)
            return Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        logo = Image.open(logo_path).convert("RGBA")
        if logo.height > max_h:
            scale = max_h / logo.height
            logo = logo.resize((max(1, int(logo.width * scale)), max_h), Image.LANCZOS)
        return logo
    except Exception as exc:
        print(f"[lyplex] warning: watermark '{logo_path}' failed to load: {exc}")
        return None


def _compose_corner_overlay(
    logo: Image.Image,
    width: int,
    height: int,
    position: str,
    margin: int,
) -> Image.Image:
    """Paste logo onto a transparent canvas at the named corner (TL/TR/BL/BR)."""
    lw, lh = logo.size
    pos = position.upper()
    x = margin if "L" in pos else width - lw - margin
    y = margin if "T" in pos else height - lh - margin
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay.paste(logo, (x, y), logo)
    return overlay


def build_watermark_overlay(
    width: int,
    height: int,
    params: WatermarkParams,
) -> Image.Image | None:
    """Return a fixed RGBA overlay with the logo pasted at a corner. None if no path or load fails."""
    if not params.path:
        return None

    max_h = params.max_height or max(20, height // 8)
    logo = _load_logo(params.path, max_h)
    if logo is None:
        return None

    if params.opacity < 1.0 - 1e-6:
        logo.putalpha(logo.getchannel('A').point(lambda v: int(v * params.opacity)))

    return _compose_corner_overlay(logo, width, height, params.position, max(8, height // 60))

# ---------------------------------------------------------------------------
# LilyPond compile
# ---------------------------------------------------------------------------

def _compile_lilypond(patched_source: str, basename: str, workdir: str, lilypond_exe: str | None = None) -> None:
    ly_file = Path(workdir) / f"{basename}.ly"
    ly_file.write_text(patched_source, encoding="utf-8")

    lilypond = _require_binary("lilypond", lilypond_exe)
    cmd = [lilypond, "--svg", "-dpoint-and-click", "-dno-use-paper-size-for-page", str(ly_file)]
    result = subprocess.run(
        cmd,
        cwd=workdir,
        capture_output=True,
        text=True,
        **_WIN_NO_WINDOW,
    )
    if result.stdout.strip():
        print(result.stdout.rstrip())
    if result.stderr.strip():
        print(result.stderr.rstrip())
    if result.returncode != 0:
        raise RuntimeError(
            f"LilyPond compilation failed (exit {result.returncode})"
        )

def compile_svg(source: str, workdir: str, lilypond_exe: str | None = None, bar_numbers: bool = True) -> list[Path]:
    """Compile SVG and return list of page paths sorted by page number.

    LilyPond naming: single page → score-svg.svg; multi-page → score-svg-1.svg, score-svg-2.svg, ...
    (scm/framework-svg.scm: file-suffix is empty when page-count=1, else '-N')
    """
    patched = patch_ly_svg(source, bar_numbers=bar_numbers)
    _compile_lilypond(patched, "score-svg", workdir, lilypond_exe)

    def _page_num(p: Path) -> int:
        m = re.search(r"-(\d+)$", p.stem)
        return int(m.group(1)) if m else 0  # 0 = no suffix = single page

    svgs = sorted(Path(workdir).glob("score-svg*.svg"), key=_page_num)
    if not svgs:
        svgs = sorted(Path(workdir).glob("*.svg"), key=_page_num)
    if svgs:
        return svgs
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

def _crop_svg_to_content(
    svg_path: Path, svg_root, max_x_svgu: float, padding: float = 0.05
) -> tuple[Path, object]:
    """Rewrite SVG width/viewBox to content extent + padding fraction.

    Returns (new_path, new_root). render_dpi is unchanged (depends only on height).
    px_per_svgu must be recomputed from the returned root.
    """
    vb = svg_root.get("viewBox", "0 0 1 1").split()
    vb_x, vb_y = float(vb[0]), float(vb[1])
    old_vb_w, vb_h = float(vb[2]), float(vb[3])
    old_width_mm = _parse_mm(svg_root.get("width", "0mm"))

    new_vb_w = max((max_x_svgu - vb_x) * (1.0 + padding), 1.0)
    new_width_mm = old_width_mm * new_vb_w / old_vb_w

    svg_root.set("width", f"{new_width_mm:.2f}mm")
    svg_root.set("viewBox", f"{vb_x:.4f} {vb_y:.4f} {new_vb_w:.4f} {vb_h:.4f}")

    cropped = svg_path.with_name("strip-cropped.svg")
    etree.ElementTree(svg_root).write(
        str(cropped), xml_declaration=True, encoding="utf-8"
    )
    print(f"[lyplex] SVG cropped: {old_width_mm:.0f}mm -> {new_width_mm:.0f}mm "
          f"({new_width_mm/old_width_mm*100:.0f}% of strip)")
    return cropped, svg_root

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
    note_ons: list[tuple[int, int, int]]  # (tick_on, pitch, duration_ticks)
    total_duration_ticks: int

def _parse_midi_tracks(midi_file: mido.MidiFile) -> list[TrackNoteEvents]:
    results: list[TrackNoteEvents] = []

    for i, track in enumerate(midi_file.tracks):
        note_ons: list[tuple[int, int, int]] = []
        abs_tick = 0
        last_tick = 0
        active: dict[int, int] = {}  # pitch → on_tick
        total_dur = 0

        for msg in track:
            abs_tick += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                active[msg.note] = abs_tick
            elif msg.type in ("note_off", "note_on") and msg.velocity == 0:
                if msg.note in active:
                    on_tick = active.pop(msg.note)
                    dur = abs_tick - on_tick
                    note_ons.append((on_tick, msg.note, dur))
                    total_dur += dur
            last_tick = abs_tick

        # notes with no note_off (end of track)
        for pitch, on_tick in active.items():
            dur = max(1, last_tick - on_tick)
            note_ons.append((on_tick, pitch, dur))
            total_dur += dur

        if note_ons:
            note_ons.sort(key=lambda e: e[0])
            results.append(TrackNoteEvents(
                track_index=i,
                note_ons=note_ons,
                total_duration_ticks=total_dur,
            ))

    return results

def _parse_time_signature(midi_file: mido.MidiFile) -> tuple[int, int]:
    """Return (numerator, denominator) from first time_signature meta message."""
    for track in midi_file.tracks:
        for msg in track:
            if msg.type == "time_signature":
                return msg.numerator, msg.denominator
    return 4, 4

def extract_timing_midi(midi_path: Path) -> tuple[list[tuple[int, int]], list[tuple[int, float, int]], int, tuple[int, int]]:
    """
    Returns (note_ons, tempo_map, ticks_per_beat, time_sig).
    note_ons: [(tick, pitch), ...] from the staff with longest total duration.
    tempo_map: [(tick, ms, tempo_us), ...] checkpoints.
    time_sig: (numerator, denominator)
    """
    midi_file = mido.MidiFile(str(midi_path))
    tempo_map = _build_tempo_map(midi_file)
    tracks = _parse_midi_tracks(midi_file)
    time_sig = _parse_time_signature(midi_file)

    if not tracks:
        raise RuntimeError("No note events found in timing MIDI.")

    # Staff with most unique onset ticks drives timing map.
    # Most-unique-ticks favours the melody over chord/accompaniment tracks whose
    # multi-voice chords inflate total_duration_ticks while having fewer distinct
    # onset positions (whole/half note chords share a tick across all chord tones).
    driving_track = max(tracks, key=lambda t: len({e[0] for e in t.note_ons}))
    note_ons = sorted(driving_track.note_ons, key=lambda e: e[0])

    return note_ons, tempo_map, midi_file.ticks_per_beat, time_sig

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
    # Group anchors by x (same beat moment — all staves, notes align vertically)
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
        y = max_anchor.y
        tick = midi_groups[i][0][0]
        ms = _tick_to_ms(tick, tempo_map, ticks_per_beat)
        max_dur_ticks = max(e[2] for e in midi_groups[i])
        off_ms = _tick_to_ms(tick + max_dur_ticks, tempo_map, ticks_per_beat)
        timing_map.append(TimingEntry(ms=ms, x=x, y=y, duration_ms=off_ms - ms))

    return timing_map


def _interp_timing_map(ms: float, timing_map: list[TimingEntry], ms_keys: list[float]) -> tuple[float, float]:
    """Return (x, y) linearly interpolated from timing_map at ms."""
    if ms <= timing_map[0].ms:
        return timing_map[0].x, timing_map[0].y
    if ms >= timing_map[-1].ms:
        return timing_map[-1].x, timing_map[-1].y
    i = bisect_left(ms_keys, ms) - 1
    i = max(0, min(i, len(timing_map) - 2))
    t0, x0, y0 = timing_map[i].ms, timing_map[i].x, timing_map[i].y
    t1, x1, y1 = timing_map[i + 1].ms, timing_map[i + 1].x, timing_map[i + 1].y
    progress = (ms - t0) / (t1 - t0) if t1 != t0 else 0.0
    return x0 + (x1 - x0) * progress, y0 + (y1 - y0) * progress


def build_bar_timing_map(
    note_timing_map: list[TimingEntry],
    tempo_map: list[tuple[int, float, int]],
    ticks_per_beat: int,
    time_sig: tuple[int, int] = (4, 4),
) -> list[TimingEntry]:
    """Downsample note-level timing map to bar boundaries.

    One entry per bar start: x/y interpolated from note_timing_map.
    Granularity = one scroll step per bar, regardless of note density.
    """
    numerator, denominator = time_sig
    ticks_per_bar = int(round(ticks_per_beat * numerator * 4 / denominator))
    if ticks_per_bar <= 0:
        return note_timing_map

    last_ms = note_timing_map[-1].ms
    ms_keys = [e.ms for e in note_timing_map]

    bar_entries: list[TimingEntry] = []
    bar_tick = 0
    while True:
        bar_ms = _tick_to_ms(bar_tick, tempo_map, ticks_per_beat)
        if bar_ms > last_ms + 500:
            break
        x, y = _interp_timing_map(bar_ms, note_timing_map, ms_keys)
        bar_entries.append(TimingEntry(ms=bar_ms, x=x, y=y))
        bar_tick += ticks_per_bar

    return bar_entries if bar_entries else note_timing_map

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
    cairosvg.svg2png(url=str(svg_path), write_to=str(out_path), dpi=render_dpi,
                     background_color="white")


def _crop_strip_height(img: Image.Image, padding_px: int = 8) -> Image.Image:
    """Crop vertical whitespace: paper-height may exceed actual content height.

    Inverts the grayscale image so white→0 and ink→positive, then uses
    getbbox() to find the bounding box of non-white content. Pads by
    padding_px and ensures H.264-compatible even height.
    """
    inverted = img.convert("L").point(lambda p: 255 - p)
    bbox = inverted.getbbox()
    if not bbox:
        return img
    top = max(0, bbox[1] - padding_px)
    bottom = min(img.height, bbox[3] + padding_px)
    new_h = bottom - top
    if new_h % 2 != 0:
        if bottom < img.height:
            bottom += 1
        else:
            top = max(0, top - 1)
    cropped = img.crop((0, top, img.width, bottom))
    if cropped.height != img.height:
        print(f"[lyplex] auto-cropped strip height: {img.height}px -> {cropped.height}px")
    return cropped

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
    result = subprocess.run(cmd, capture_output=True, text=True, **_WIN_NO_WINDOW)
    if result.returncode != 0:
        raise RuntimeError(f"fluidsynth failed:\n{result.stderr}")

# ---------------------------------------------------------------------------
# Metronome click synthesis
# ---------------------------------------------------------------------------

_CLICK_SAMPLE_RATE = 44100

_DEFAULT_ACCENT = ClickParams(freq_hz=1500.0, waveform="sine", duration_ms=20.0, amplitude=0.6)
_DEFAULT_BEAT   = ClickParams(freq_hz=1000.0, waveform="sine", duration_ms=20.0, amplitude=0.4)


def _make_click_burst(p: ClickParams) -> list[float]:
    """Pre-render one click burst as a float list (reused for every beat of the same type)."""
    n = max(1, int(p.duration_ms / 1000.0 * _CLICK_SAMPLE_RATE))
    phase_step = 2 * math.pi * p.freq_hz / _CLICK_SAMPLE_RATE
    burst = []
    for k in range(n):
        env = math.sin(math.pi * k / n)
        phase = phase_step * k
        if p.waveform == "square":
            s = 1.0 if math.sin(phase) >= 0 else -1.0
        elif p.waveform == "triangle":
            s = 2 / math.pi * math.asin(math.sin(phase))
        elif p.waveform == "saw":
            s = 2 * ((p.freq_hz * k / _CLICK_SAMPLE_RATE) % 1.0) - 1.0
        else:
            s = math.sin(phase)
        burst.append(p.amplitude * env * s)
    return burst


_CLICK_PRE_ROLL_MS = 500.0  # silence before first count-in click; prevents t=0 clip


def render_click_wav(
    tempo_map: list[tuple[int, float, int]],
    ticks_per_beat: int,
    time_sig: tuple[int, int],
    total_ms: float,
    out_path: Path,
    tempo_multiplier: float = 1.0,
    accent_params: ClickParams | None = None,
    beat_params: ClickParams | None = None,
    count_in_bars: int = 0,
) -> ClickResult:
    """Synthesize a click-track WAV.  Returns ClickResult with wav_path and count-in duration.

    The WAV starts with _CLICK_PRE_ROLL_MS of silence so the very first click is
    never clipped by a player.  count_in_ms in the returned ClickResult includes
    this pre-roll so the music audio is delayed by the same amount.
    """
    ap = accent_params or _DEFAULT_ACCENT
    bp = beat_params   or _DEFAULT_BEAT

    numerator, denominator = time_sig
    ticks_per_bar = int(ticks_per_beat * numerator * 4 / denominator)

    def t2ms(tick: int) -> float:
        return _tick_to_ms(tick, tempo_map, ticks_per_beat)

    # count_in_ms is the musical silence before beat 1 (count-in bars).
    # pre_roll shifts the whole WAV so t=0 is never sample 0.
    count_in_music_ms = 0.0
    clicks: list[tuple[float, bool]] = []

    if count_in_bars > 0:
        bar_ms = t2ms(ticks_per_bar) / tempo_multiplier
        count_in_music_ms = count_in_bars * bar_ms
        count_in_ticks = count_in_bars * ticks_per_bar
        for t in range(count_in_ticks, 0, -ticks_per_beat):
            t_ms = count_in_music_ms - t2ms(t) / tempo_multiplier + _CLICK_PRE_ROLL_MS
            clicks.append((t_ms, t % ticks_per_bar == 0))

    last_cp_tick, last_cp_ms, last_cp_tempo_us = tempo_map[-1]
    extra_ticks = int(max(0.0, total_ms - last_cp_ms) * 1000 / last_cp_tempo_us * ticks_per_beat)
    last_tick = last_cp_tick + extra_ticks

    for t in range(0, last_tick + ticks_per_beat, ticks_per_beat):
        t_ms = t2ms(t) / tempo_multiplier + count_in_music_ms
        if t_ms > total_ms + count_in_music_ms + 500:
            break
        clicks.append((t_ms + _CLICK_PRE_ROLL_MS, t % ticks_per_bar == 0))

    # Total count-in delay seen by the muxer = musical count-in + pre-roll.
    count_in_ms = count_in_music_ms + _CLICK_PRE_ROLL_MS

    wav_total_ms = total_ms + count_in_ms
    n_samples = int((wav_total_ms / 1000.0 + 1.0) * _CLICK_SAMPLE_RATE)

    burst_a = _make_click_burst(ap)
    burst_b = _make_click_burst(bp)
    buf = array.array('f', [0.0] * n_samples)

    for t_ms, is_accent in clicks:
        burst = burst_a if is_accent else burst_b
        start = int(t_ms / 1000.0 * _CLICK_SAMPLE_RATE)
        for k, s in enumerate(burst):
            idx = start + k
            if idx >= n_samples:
                break
            buf[idx] += s

    packed = array.array('h', (max(-32768, min(32767, int(s * 32767))) for s in buf))
    with wave.open(str(out_path), 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_CLICK_SAMPLE_RATE)
        wf.writeframes(packed.tobytes())

    return ClickResult(wav_path=out_path, count_in_ms=count_in_ms)


# ---------------------------------------------------------------------------
# MP4 export
# ---------------------------------------------------------------------------

def _build_audio_cmd(
    click_wav_path: Path | None,
    delay_ms: int,
    audio_filters: str | None,
) -> list[str]:
    """Return ffmpeg audio-related args (extra -i inputs + filter flags)."""
    args: list[str] = []
    if click_wav_path is not None:
        args += ["-i", str(click_wav_path)]
        # atempo before adelay: adelay operates in output-domain ms after speed change,
        # so the delay stays equal to count_in_ms regardless of tempo_multiplier.
        if audio_filters:
            segments = [
                f"[1:a]{audio_filters}[musicf]",
                f"[musicf]adelay={delay_ms}|{delay_ms}[music]",
            ]
        else:
            segments = [f"[1:a]adelay={delay_ms}|{delay_ms}[music]"]
        # normalize=0 requires ffmpeg 4.4+; omit for compatibility (amix will halve volumes)
        segments.append(f"[music][2:a]amix=inputs=2:duration=longest")
        args += ["-filter_complex", ";".join(segments)]
    elif delay_ms > 0:
        if audio_filters:
            chain = f"[1:a]{audio_filters},adelay={delay_ms}|{delay_ms}"
        else:
            chain = f"[1:a]adelay={delay_ms}|{delay_ms}"
        args += ["-filter_complex", chain]
    elif audio_filters:
        args += ["-filter:a", audio_filters]
    return args


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
    cursor_line: bool = True,
    cursor_color: tuple[int, int, int] = (220, 50, 50),
    cursor_width: int = 2,
    trail: bool = True,
    note_highlight: bool = True,
    highlight_map: list[TimingEntry] | None = None,
    highlight_color: tuple[int, int, int] = (50, 120, 220),
    title_footer_overlay: Image.Image | None = None,
    watermark_overlay: Image.Image | None = None,
    fade_frames: int = 0,
    click_result: ClickResult | None = None,
) -> None:
    ffmpeg = _require_binary("ffmpeg", ffmpeg_exe)

    click_wav_path = click_result.wav_path if click_result else None
    count_in_ms = click_result.count_in_ms if click_result else 0.0

    # Duration = count-in + last note ms + 2s tail
    duration_ms = count_in_ms + timing_map[-1].ms + 2000.0
    n_frames = int(duration_ms / 1000.0 * fps) + 1
    fade_frames = min(fade_frames, n_frames // 2)

    audio_filters = _atempo_filter(atempo) if abs(atempo - 1.0) > 1e-6 else None

    # Music WAV delayed by count_in_ms; click WAV already starts at t=0
    delay_ms = int(count_in_ms)
    ffmpeg_cmd = [
        ffmpeg, "-y",
        "-framerate", str(fps),
        "-f", "image2pipe",
        "-vcodec", "ppm",
        "-i", "pipe:0",
        "-i", str(wav_path),
    ]
    ffmpeg_cmd += _build_audio_cmd(click_wav_path, delay_ms, audio_filters)
    ffmpeg_cmd += ["-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
                   "-shortest", str(out_path)]

    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, **_WIN_NO_WINDOW)

    ms_keys = [e.ms for e in timing_map]
    cx = int(width * CURSOR_POSITION)
    HL_RADIUS = max(6, height // 90)

    # Pre-build loop-invariant tint overlay (played region, semi-transparent blue)
    if trail:
        _tint_base = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        ImageDraw.Draw(_tint_base).rectangle([(0, 0), (cx - 1, height - 1)], fill=(100, 140, 220, 35))

    # Note highlight setup
    _hl_map = highlight_map if (note_highlight and highlight_map) else None
    if _hl_map:
        hl_ms_keys = [e.ms for e in _hl_map]
        max_hl_dur = max((e.duration_ms for e in _hl_map), default=2000.0)
        hl_r, hl_g, hl_b = highlight_color
    else:
        hl_ms_keys = None
        max_hl_dur = 0.0

    needs_overlay = trail or bool(_hl_map)

    # Pre-composite fixed overlays into one image (done once outside frame loop)
    fixed_overlay: Image.Image | None = None
    if title_footer_overlay is not None or watermark_overlay is not None:
        _combined = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        if title_footer_overlay is not None:
            _combined = Image.alpha_composite(_combined, title_footer_overlay)
        if watermark_overlay is not None:
            _combined = Image.alpha_composite(_combined, watermark_overlay)
        fixed_overlay = _combined

    try:
        for frame_n in range(n_frames):
            t_ms = frame_n / fps * 1000.0 - count_in_ms
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
                padded = Image.new("RGB", (width, height), (255, 255, 255))
                padded.paste(frame, (0, 0))
                frame = padded

            if needs_overlay or cursor_line:
                if needs_overlay:
                    overlay = _tint_base.copy() if trail else Image.new("RGBA", (width, height), (0, 0, 0, 0))
                    ov = ImageDraw.Draw(overlay)

                    if trail:
                        i_trail = bisect_left(ms_keys, t_ms)
                        past = timing_map[max(0, i_trail - TRAIL_DOTS):i_trail]
                        n_past = len(past)
                        for idx, entry in enumerate(past):
                            ex_px = int(entry.x * px_per_svgu) - left
                            ey_px = int(entry.y * px_per_svgu)
                            r = TRAIL_DOT_RADIUS
                            if (-r <= ex_px <= width + r
                                    and -r <= ey_px <= height + r):
                                alpha = int(200 * (idx + 1) / n_past) if n_past else 0
                                ov.ellipse(
                                    [(ex_px - r, ey_px - r), (ex_px + r, ey_px + r)],
                                    fill=(220, 80, 50, alpha),
                                )

                    if _hl_map and hl_ms_keys is not None:
                        i_lo = max(0, bisect_left(hl_ms_keys, t_ms - max_hl_dur) - 1)
                        for entry in _hl_map[i_lo:]:
                            if entry.ms > t_ms:
                                break
                            if entry.duration_ms > 0 and entry.ms + entry.duration_ms > t_ms:
                                ex_px = int(entry.x * px_per_svgu) - left
                                ey_px = int(entry.y * px_per_svgu)
                                r2 = HL_RADIUS * 2
                                if (-r2 <= ex_px <= width + r2
                                        and -r2 <= ey_px <= height + r2):
                                    ov.ellipse(
                                        [(ex_px - HL_RADIUS, ey_px - HL_RADIUS),
                                         (ex_px + HL_RADIUS, ey_px + HL_RADIUS)],
                                        fill=(hl_r, hl_g, hl_b, 150),
                                    )

                    frame = Image.alpha_composite(frame.convert("RGBA"), overlay).convert("RGB")

                if cursor_line:
                    draw = ImageDraw.Draw(frame)
                    draw.line([(cx, 0), (cx, height - 1)], fill=cursor_color, width=cursor_width)

            if fixed_overlay is not None:
                frame = Image.alpha_composite(frame.convert("RGBA"), fixed_overlay).convert("RGB")

            if fade_frames > 0:
                if frame_n < fade_frames:
                    alpha = frame_n / fade_frames
                elif frame_n >= n_frames - fade_frames:
                    alpha = (n_frames - 1 - frame_n) / fade_frames
                else:
                    alpha = 1.0
                if alpha < 1.0:
                    black = Image.new("RGB", (width, height), (0, 0, 0))
                    frame = Image.blend(black, frame.convert("RGB"), alpha)

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
    cursor_line: bool = True,
    cursor_color: tuple[int, int, int] = (220, 50, 50),
    cursor_width: int = 2,
    trail: bool = True,
    note_highlight: bool = True,
    highlight_color: tuple[int, int, int] = (50, 120, 220),
    overlay_title: bool = False,
    overlay_footer: bool = False,
    use_bar_timing: bool = True,
    bar_numbers: bool = True,
    fade_frames: int = 0,
    watermark: WatermarkParams | None = None,
    metronome: bool = False,
    click_accent: ClickParams | None = None,
    click_beat: ClickParams | None = None,
    count_in_bars: int = 0,  # 0-2
) -> None:
    # Preflight
    _require_binary("lilypond", lilypond_exe)
    _require_binary("ffmpeg", ffmpeg_exe)
    _require_binary("fluidsynth", fluidsynth_exe)
    _require_soundfont(sf2_path)

    source = Path(ly_path).read_text(encoding="utf-8")
    _require_version_declaration(source, ly_path)

    header = _extract_header(source)
    needs_audio_midi = True  # timing MIDI strips ties; audio always uses separate patch

    workdir = tempfile.mkdtemp(prefix="lyplex_")
    try:
        print(f"[lyplex] workdir: {workdir}")

        # Compile
        print("[lyplex] compiling SVG...")
        svg_paths = compile_svg(source, workdir, lilypond_exe, bar_numbers=bar_numbers)
        if len(svg_paths) > 1:
            print(f"[lyplex] {len(svg_paths)} SVG pages — concatenating strips")

        print("[lyplex] compiling timing MIDI...")
        timing_midi_path = compile_timing_midi(source, workdir, lilypond_exe)

        if needs_audio_midi:
            print("[lyplex] compiling audio MIDI (unfolding repeats)...")
            audio_midi_path = compile_audio_midi(source, workdir, lilypond_exe)
        else:
            audio_midi_path = timing_midi_path

        # Parse all SVG pages; extract anchors with cumulative x-offsets across pages.
        svg_roots = [etree.parse(str(p)).getroot() for p in svg_paths]
        print("[lyplex] extracting SVG anchors...")
        anchors = []
        x_offset_svgu = 0.0
        for root in svg_roots:
            for a in _extract_anchors_from_root(root):
                anchors.append(dc_replace(a, x=a.x + x_offset_svgu))
            vb = root.get("viewBox", "0 0 0 0").split()
            x_offset_svgu += float(vb[2]) if len(vb) >= 3 else 0.0
        if not anchors:
            raise RuntimeError("No note anchors found in SVG. Check \\pointAndClickTypes injection.")

        print("[lyplex] parsing timing MIDI...")
        note_ons, tempo_map, ticks_per_beat, time_sig = extract_timing_midi(timing_midi_path)

        # Timing map
        print("[lyplex] building timing map...")
        note_timing_map = build_timing_map(anchors, note_ons, tempo_map, ticks_per_beat)
        if not note_timing_map:
            raise RuntimeError("Timing map is empty after correlation.")

        if use_bar_timing:
            print(f"[lyplex] building bar-level timing map (time sig {time_sig[0]}/{time_sig[1]})...")
            timing_map = build_bar_timing_map(note_timing_map, tempo_map, ticks_per_beat, time_sig)
            print(f"[lyplex] bar timing map: {len(timing_map)} bars")
        else:
            timing_map = note_timing_map

        if abs(tempo_multiplier - 1.0) > 1e-6:
            timing_map = [dc_replace(e, ms=e.ms / tempo_multiplier) for e in timing_map]

        # Crop last page to content width (removes trailing paper-width whitespace).
        last_anchors_local = _extract_anchors_from_root(svg_roots[-1])
        if last_anchors_local:
            max_x_last = max(a.x for a in last_anchors_local)
            svg_paths[-1], svg_roots[-1] = _crop_svg_to_content(svg_paths[-1], svg_roots[-1], max_x_last)

        # Scale — px_per_svgu is constant across pages (same LilyPond compile).
        render_dpi, px_per_svgu = _svg_scale_from_root(svg_roots[0], height)

        # Render each page to PNG, then concatenate horizontally.
        strip_png = Path(workdir) / "strip.png"
        print(f"[lyplex] rendering strip PNG at {render_dpi:.1f} dpi...")
        if len(svg_paths) == 1:
            render_strip_png(svg_paths[0], render_dpi, strip_png)
            strip_img = Image.open(str(strip_png)).convert("RGB")
        else:
            page_imgs: list[Image.Image] = []
            for i, sp in enumerate(svg_paths):
                page_png = Path(workdir) / f"strip-{i}.png"
                render_strip_png(sp, render_dpi, page_png)
                page_imgs.append(Image.open(str(page_png)).convert("RGB"))
            total_w = sum(img.width for img in page_imgs)
            page_h = max(img.height for img in page_imgs)
            strip_img = Image.new("RGB", (total_w, page_h), (255, 255, 255))
            x_px = 0
            for img in page_imgs:
                strip_img.paste(img, (x_px, 0))
                x_px += img.width
            strip_img.save(str(strip_png))

        # Auto-crop vertical whitespace (paper-height=250mm often exceeds content height).
        # Updates height so overlays, encode_mp4, and RAM estimate use actual dimensions.
        strip_img = _crop_strip_height(strip_img)
        height = strip_img.height

        _strip_ram_mb = strip_img.width * height * 3 / (1024 * 1024)
        if _strip_ram_mb > 400:
            print(f"[lyplex] WARNING: strip PNG ~{_strip_ram_mb:.0f} MB "
                  f"({strip_img.width}×{height}px). Very long score — may exhaust RAM.")

        # Audio
        wav_path = Path(workdir) / "audio.wav"
        print("[lyplex] rendering audio...")
        render_audio_wav(audio_midi_path, sf2_path, wav_path, fluidsynth_exe)

        # Metronome click track
        click_result: ClickResult | None = None
        if metronome:
            click_wav = Path(workdir) / "click.wav"
            print("[lyplex] synthesizing metronome click track...")
            # Use the rendered audio WAV duration as total_ms so the click track
            # covers the full piece even when unfolded repeats make the audio MIDI
            # longer than the timing MIDI (which drives note_timing_map).
            with wave.open(str(wav_path), 'r') as _wf:
                _audio_total_ms = _wf.getnframes() / _wf.getframerate() * 1000.0
            click_result = render_click_wav(
                tempo_map, ticks_per_beat, time_sig,
                total_ms=_audio_total_ms,
                out_path=click_wav,
                tempo_multiplier=tempo_multiplier,
                accent_params=click_accent,
                beat_params=click_beat,
                count_in_bars=count_in_bars,
            )
            if click_result.count_in_ms > 0:
                print(f"[lyplex] count-in: {count_in_bars} bar(s) = {click_result.count_in_ms:.0f} ms")

        # Build fixed overlays (done once, composited every frame)
        tf_overlay = build_title_footer_overlay(width, height, header, overlay_title, overlay_footer)
        wm_overlay = build_watermark_overlay(width, height, watermark or WatermarkParams())

        # Encode
        print("[lyplex] encoding MP4...")
        encode_mp4(
            strip_img, timing_map, px_per_svgu,
            wav_path, Path(out_path),
            width=width, height=height, fps=fps,
            atempo=tempo_multiplier,
            ffmpeg_exe=ffmpeg_exe,
            cursor_line=cursor_line,
            cursor_color=cursor_color,
            cursor_width=cursor_width,
            trail=trail,
            note_highlight=note_highlight,
            highlight_map=note_timing_map,
            highlight_color=highlight_color,
            title_footer_overlay=tf_overlay,
            watermark_overlay=wm_overlay,
            fade_frames=fade_frames,
            click_result=click_result,
        )

        print(f"[lyplex] done: {out_path}")

    finally:
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
    parser.add_argument("--no-bar-timing", action="store_true",
                        help="Use note-level timing instead of bar-level")
    parser.add_argument("--no-cursor", dest="cursor", action="store_false", default=True, help="Hide cursor line")
    parser.add_argument("--no-trail", dest="trail", action="store_false", default=True, help="Hide past-beat trail dots")
    parser.add_argument("--no-highlight", dest="highlight", action="store_false", default=True, help="Hide active note highlight")
    parser.add_argument("--no-bar-numbers", action="store_true", help="Hide bar numbers in score")
    parser.add_argument("--metronome", action="store_true", help="Add metronome click track")
    parser.add_argument("--count-in", type=int, default=0, metavar="BARS",
                        help="Count-in bars before music (requires --metronome)")
    parser.add_argument("--tempo", type=float, default=1.0, metavar="MULT",
                        help="Tempo multiplier (e.g. 0.75 = 75%%)")
    args = parser.parse_args()

    generate_mp4(
        ly_path=args.ly_file,
        sf2_path=args.sf2_file,
        out_path=args.output,
        width=args.width,
        height=args.height,
        fps=args.fps,
        use_bar_timing=not args.no_bar_timing,
        cursor_line=args.cursor,
        trail=args.trail,
        note_highlight=args.highlight,
        bar_numbers=not args.no_bar_numbers,
        metronome=args.metronome,
        count_in_bars=args.count_in,
        tempo_multiplier=args.tempo,
    )
