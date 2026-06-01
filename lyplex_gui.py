"""
lyplex_gui.py — accessible wxPython GUI for LyPlex pipeline
Run: python lyplex_gui.py
"""

from __future__ import annotations

import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path

import wx

from lyplex_tool import DEFAULT_FPS, DEFAULT_HEIGHT, DEFAULT_WIDTH, ClickParams, WatermarkParams, generate_mp4

HERE = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent

def _default(rel: str) -> str:
    """Return absolute path for a bundled file if it exists, else empty string."""
    p = HERE / rel
    return str(p) if p.exists() else ""

COLOR_PRESETS: list[tuple[str, tuple[int, int, int]]] = [
    ("Red",    (220,  50,  50)),
    ("Blue",   ( 50, 120, 220)),
    ("Green",  ( 50, 180,  80)),
    ("Yellow", (240, 200,  30)),
    ("Cyan",   ( 40, 200, 220)),
    ("Orange", (240, 130,  40)),
    ("White",  (255, 255, 255)),
    ("Black",  (  0,   0,   0)),
    ("Purple", (160,  60, 200)),
    ("Pink",   (240, 100, 160)),
]
_PRESET_NAMES = [name for name, _ in COLOR_PRESETS]

def _parse_color(choice: wx.Choice, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    i = choice.GetSelection()
    return COLOR_PRESETS[i][1] if 0 <= i < len(COLOR_PRESETS) else fallback


def _spin_double(parent: wx.Window, lo: float, hi: float, val: float, inc: float, name: str) -> wx.SpinCtrlDouble:
    c = wx.SpinCtrlDouble(parent, min=lo, max=hi, initial=val, inc=inc, name=name)
    c.SetDigits(2)
    return c


@dataclass
class PipelineConfig:
    ly: str
    sf2: str
    out_mp4: str
    width: int
    height: int
    fps: int
    tempo: float
    cursor_line: bool
    cursor_color: tuple[int, int, int]
    cursor_width: int
    note_highlight: bool
    highlight_color: tuple[int, int, int]
    trail: bool
    overlay_title: bool
    overlay_footer: bool
    use_bar_timing: bool
    bar_numbers: bool
    metronome: bool
    click_a: ClickParams
    click_b: ClickParams
    count_in_bars: int
    fade_frames: int
    watermark: WatermarkParams
    fill_height: bool
    lilypond_exe: str | None
    ffmpeg_exe: str | None
    fluidsynth_exe: str | None


# ---------------------------------------------------------------------------
# Metronome settings dialog
# ---------------------------------------------------------------------------

class MetronomeDialog(wx.Dialog):
    _WAVEFORMS = ["sine", "square", "triangle", "saw"]

    def __init__(self, parent, click_a: ClickParams, click_b: ClickParams, count_in: int):
        super().__init__(parent, title="Metronome Settings",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        panel = wx.Panel(self)
        grid = wx.FlexGridSizer(cols=3, hgap=8, vgap=6)
        grid.AddGrowableCol(1, 1)

        def _section(title: str) -> None:
            st = wx.StaticText(panel, label=title)
            st.SetFont(st.GetFont().Bold())
            grid.Add(st, 0, wx.TOP | wx.ALIGN_CENTER_VERTICAL, 6)
            grid.AddSpacer(0)
            grid.AddSpacer(0)

        def _row(label: str, ctrl, hint: str = "") -> None:
            grid.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(ctrl, 0, wx.EXPAND)
            grid.Add(wx.StaticText(panel, label=hint) if hint else (0, 0),
                     0, wx.ALIGN_CENTER_VERTICAL)

        def _wf_idx(p: ClickParams) -> int:
            try:
                return self._WAVEFORMS.index(p.waveform)
            except ValueError:
                return 0

        _section("Accent click  (beat 1)")
        self._a_freq = wx.SpinCtrl(panel, min=100, max=8000, initial=int(click_a.freq_hz), name="Accent frequency")
        _row("Frequency:", self._a_freq, "Hz")
        self._a_wave = wx.Choice(panel, choices=self._WAVEFORMS, name="Accent waveform")
        self._a_wave.SetSelection(_wf_idx(click_a))
        _row("Waveform:", self._a_wave)
        self._a_dur = wx.SpinCtrl(panel, min=5, max=200, initial=int(click_a.duration_ms), name="Accent duration")
        _row("Duration:", self._a_dur, "ms")
        self._a_amp = _spin_double(panel, 0.05, 1.0, click_a.amplitude, 0.05, "Accent amplitude")
        _row("Amplitude:", self._a_amp, "0.05 – 1.0")

        _section("Beat click  (beats 2, 3, …)")
        self._b_freq = wx.SpinCtrl(panel, min=100, max=8000, initial=int(click_b.freq_hz), name="Beat frequency")
        _row("Frequency:", self._b_freq, "Hz")
        self._b_wave = wx.Choice(panel, choices=self._WAVEFORMS, name="Beat waveform")
        self._b_wave.SetSelection(_wf_idx(click_b))
        _row("Waveform:", self._b_wave)
        self._b_dur = wx.SpinCtrl(panel, min=5, max=200, initial=int(click_b.duration_ms), name="Beat duration")
        _row("Duration:", self._b_dur, "ms")
        self._b_amp = _spin_double(panel, 0.05, 1.0, click_b.amplitude, 0.05, "Beat amplitude")
        _row("Amplitude:", self._b_amp, "0.05 – 1.0")

        _section("Count-in")
        self._count_in_spin = wx.SpinCtrl(panel, min=0, max=2, initial=count_in, name="Count-in bars")
        _row("Bars:", self._count_in_spin, "0 = no count-in")

        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(grid, 0, wx.EXPAND | wx.ALL, 12)
        root.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        root.Add(btns, 0, wx.EXPAND | wx.ALL, 8)
        panel.SetSizer(root)
        root.Fit(self)

    def get_values(self) -> tuple[ClickParams, ClickParams, int]:
        a = ClickParams(
            freq_hz=float(self._a_freq.GetValue()),
            waveform=self._a_wave.GetStringSelection(),
            duration_ms=float(self._a_dur.GetValue()),
            amplitude=self._a_amp.GetValue(),
        )
        b = ClickParams(
            freq_hz=float(self._b_freq.GetValue()),
            waveform=self._b_wave.GetStringSelection(),
            duration_ms=float(self._b_dur.GetValue()),
            amplitude=self._b_amp.GetValue(),
        )
        return a, b, self._count_in_spin.GetValue()


# ---------------------------------------------------------------------------
# Watermark settings dialog
# ---------------------------------------------------------------------------

class WatermarkDialog(wx.Dialog):
    _POSITIONS = ["BR", "BL", "TR", "TL"]

    def __init__(self, parent, params: WatermarkParams):
        super().__init__(parent, title="Watermark Settings",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        panel = wx.Panel(self)
        grid = wx.FlexGridSizer(cols=3, hgap=8, vgap=8)
        grid.AddGrowableCol(1, 1)

        # Logo file picker
        grid.Add(wx.StaticText(panel, label="Logo file:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._path_tc = wx.TextCtrl(panel, value=params.path, name="Watermark logo file")
        btn_browse = wx.Button(panel, label="Browse…", size=(70, -1))
        def _on_browse(_e):
            dlg = wx.FileDialog(
                self,
                wildcard="Images (*.svg;*.png;*.jpg;*.jpeg)|*.svg;*.png;*.jpg;*.jpeg"
                         "|All files (*.*)|*.*",
                style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
            )
            if dlg.ShowModal() == wx.ID_OK:
                self._path_tc.SetValue(dlg.GetPath())
            dlg.Destroy()
        btn_browse.Bind(wx.EVT_BUTTON, _on_browse)
        sz_path = wx.BoxSizer(wx.HORIZONTAL)
        sz_path.Add(self._path_tc, 1, wx.EXPAND)
        sz_path.Add(btn_browse, 0, wx.LEFT, 4)
        grid.Add(sz_path, 1, wx.EXPAND)
        grid.Add(wx.StaticText(panel, label="(blank = no watermark)"),
                 0, wx.ALIGN_CENTER_VERTICAL)

        # Position
        pos_idx = next((i for i, p in enumerate(self._POSITIONS) if p == params.position), 0)
        grid.Add(wx.StaticText(panel, label="Position:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._pos_ch = wx.Choice(panel, choices=self._POSITIONS, name="Watermark position")
        self._pos_ch.SetSelection(pos_idx)
        grid.Add(self._pos_ch, 0)
        grid.Add(wx.StaticText(panel, label="corner of video"), 0, wx.ALIGN_CENTER_VERTICAL)

        # Opacity
        grid.Add(wx.StaticText(panel, label="Opacity:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._opacity_ctrl = _spin_double(panel, 0.05, 1.0, params.opacity, 0.05, "Watermark opacity")
        grid.Add(self._opacity_ctrl, 0)
        grid.Add(wx.StaticText(panel, label="0.05 – 1.0"), 0, wx.ALIGN_CENTER_VERTICAL)

        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(grid, 0, wx.EXPAND | wx.ALL, 12)
        root.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        root.Add(btns, 0, wx.EXPAND | wx.ALL, 8)
        panel.SetSizer(root)
        root.Fit(self)

    def get_values(self) -> WatermarkParams:
        return WatermarkParams(
            path=self._path_tc.GetValue().strip(),
            position=self._pos_ch.GetStringSelection(),
            opacity=self._opacity_ctrl.GetValue(),
        )


# ---------------------------------------------------------------------------
# Log stream — redirects print() to the log widget, handles \r progress lines
# ---------------------------------------------------------------------------

class _LogStream:
    """Redirect write() to wx callbacks, handling \\r carriage-return progress lines."""

    def __init__(self, on_newline, on_overwrite):
        self._on_newline = on_newline
        self._on_overwrite = on_overwrite
        self._buf = ""

    def write(self, text: str) -> None:
        self._buf += text
        while True:
            cr = self._buf.find("\r")
            nl = self._buf.find("\n")
            if cr == -1 and nl == -1:
                break
            if nl != -1 and (cr == -1 or nl < cr):
                line, self._buf = self._buf[:nl], self._buf[nl + 1:]
                wx.CallAfter(self._on_newline, line)
            else:
                line, self._buf = self._buf[:cr], self._buf[cr + 1:]
                wx.CallAfter(self._on_overwrite, line)

    def flush(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainFrame(wx.Frame):

    def __init__(self):
        super().__init__(None, title="LyPlex — Scrolling Sheet Music", size=(740, 900))
        self._mp4_path: str | None = None
        self._html_path: str | None = None
        self._overwriting_log_line = False
        # Metronome / watermark dialog state (updated when dialogs are accepted)
        self._click_a = ClickParams(freq_hz=1500.0, waveform="sine", duration_ms=20.0, amplitude=0.6)
        self._click_b = ClickParams(freq_hz=1000.0, waveform="sine", duration_ms=20.0, amplitude=0.4)
        self._count_in = 0
        self._watermark = WatermarkParams()
        self._build_ui()
        self.CreateStatusBar()
        self.SetStatusText("Ready.")
        self.Centre()
        self.Show()

    # ------------------------------------------------------------------
    # UI construction
    # Labels created before controls so MSAA finds the preceding Static
    # as the accessible name for each native HWND control.
    # All file/dir pickers are plain TextCtrl + Button so the TextCtrl
    # is a direct panel child — composite controls (FilePickerCtrl,
    # DirPickerCtrl, SpinCtrlDouble) bury their inner HWND one level
    # deeper, which breaks MSAA sibling-label detection.
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)

        grid = wx.FlexGridSizer(cols=3, hgap=6, vgap=8)
        grid.AddGrowableCol(1, 1)

        # --- helpers (closures over panel/grid/self) ---
        # Each helper creates the StaticText label FIRST so it precedes
        # the TextCtrl in HWND z-order — MSAA scans backward for the
        # nearest preceding Static to use as the accessible name.

        def file_row(label: str, wildcard: str,
                     default: str = "", hint: str = "") -> wx.TextCtrl:
            lbl = wx.StaticText(panel, label=label)   # FIRST — MSAA anchor
            tc  = wx.TextCtrl(panel, value=default)   # SECOND
            btn = wx.Button(panel, label="Browse…", size=(70, -1))
            def on_browse(_e, _tc=tc, _wc=wildcard):
                dlg = wx.FileDialog(self, wildcard=_wc,
                                    style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
                if dlg.ShowModal() == wx.ID_OK:
                    _tc.SetValue(dlg.GetPath())
                dlg.Destroy()
            btn.Bind(wx.EVT_BUTTON, on_browse)
            sz = wx.BoxSizer(wx.HORIZONTAL)
            sz.Add(tc, 1, wx.EXPAND)
            sz.Add(btn, 0, wx.LEFT, 4)
            grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(sz,  1, wx.EXPAND)
            grid.Add(wx.StaticText(panel, label=hint), 0, wx.ALIGN_CENTER_VERTICAL) if hint else grid.AddSpacer(0)
            return tc

        def dir_row(label: str, default: str = "", hint: str = "") -> wx.TextCtrl:
            lbl = wx.StaticText(panel, label=label)
            tc  = wx.TextCtrl(panel, value=default)
            btn = wx.Button(panel, label="Browse…", size=(70, -1))
            def on_browse(_e, _tc=tc):
                dlg = wx.DirDialog(self)
                if dlg.ShowModal() == wx.ID_OK:
                    _tc.SetValue(dlg.GetPath())
                dlg.Destroy()
            btn.Bind(wx.EVT_BUTTON, on_browse)
            sz = wx.BoxSizer(wx.HORIZONTAL)
            sz.Add(tc, 1, wx.EXPAND)
            sz.Add(btn, 0, wx.LEFT, 4)
            grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(sz,  1, wx.EXPAND)
            grid.Add(wx.StaticText(panel, label=hint), 0, wx.ALIGN_CENTER_VERTICAL) if hint else grid.AddSpacer(0)
            return tc

        def spin_double_row(label: str, min_v: float, max_v: float,
                            initial: float, inc: float, digits: int,
                            hint: str = "") -> wx.TextCtrl:
            lbl = wx.StaticText(panel, label=label)
            tc  = wx.TextCtrl(panel, value=f"{initial:.{digits}f}", size=(80, -1))
            sp  = wx.SpinButton(panel, style=wx.SP_VERTICAL)
            sp.SetRange(-32768, 32767)
            sp.SetValue(0)
            def adjust(delta: float) -> None:
                try:
                    val = float(tc.GetValue())
                except ValueError:
                    val = initial
                val = max(min_v, min(max_v, round(val + delta, digits)))
                tc.SetValue(f"{val:.{digits}f}")
                sp.SetValue(0)
            sp.Bind(wx.EVT_SPIN_UP,   lambda e: adjust(+inc))
            sp.Bind(wx.EVT_SPIN_DOWN, lambda e: adjust(-inc))
            def on_kill_focus(_e):
                try:
                    val = max(min_v, min(max_v, float(tc.GetValue())))
                    tc.SetValue(f"{val:.{digits}f}")
                except ValueError:
                    tc.SetValue(f"{initial:.{digits}f}")
                _e.Skip()
            tc.Bind(wx.EVT_KILL_FOCUS, on_kill_focus)
            sz = wx.BoxSizer(wx.HORIZONTAL)
            sz.Add(tc, 0)
            sz.Add(sp, 0)
            grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(sz,  0)
            grid.Add(wx.StaticText(panel, label=hint), 0, wx.ALIGN_CENTER_VERTICAL) if hint else grid.AddSpacer(0)
            return tc

        def chk_row(label: str, chk_label: str, hint: str = "") -> wx.CheckBox:
            grid.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            chk = wx.CheckBox(panel, label=chk_label)
            grid.Add(chk, 0)
            grid.Add(wx.StaticText(panel, label=hint), 0, wx.ALIGN_CENTER_VERTICAL) if hint else grid.AddSpacer(0)
            return chk

        def color_row(label: str, default_rgb: tuple, hint: str = "") -> wx.Choice:
            default_idx = next(
                (i for i, (_, rgb) in enumerate(COLOR_PRESETS) if rgb == default_rgb), 0
            )
            grid.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            ch = wx.Choice(panel, choices=_PRESET_NAMES, name=label.rstrip(":"))
            ch.SetSelection(default_idx)
            swatch = wx.Panel(panel, size=(20, 20))
            swatch.SetBackgroundColour(wx.Colour(*default_rgb))
            def _update_swatch(_e, _ch=ch, _sw=swatch):
                i = _ch.GetSelection()
                if 0 <= i < len(COLOR_PRESETS):
                    _sw.SetBackgroundColour(wx.Colour(*COLOR_PRESETS[i][1]))
                    _sw.Refresh()
            ch.Bind(wx.EVT_CHOICE, _update_swatch)
            sz = wx.BoxSizer(wx.HORIZONTAL)
            sz.Add(ch, 0, wx.ALIGN_CENTER_VERTICAL)
            sz.Add(swatch, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 4)
            grid.Add(sz, 0)
            grid.Add(wx.StaticText(panel, label=hint), 0, wx.ALIGN_CENTER_VERTICAL) if hint else grid.AddSpacer(0)
            return ch

        # --- file / folder rows ---

        self._ly_tc = file_row(
            "LilyPond score (.ly):",
            "LilyPond files (*.ly)|*.ly|All files (*.*)|*.*",
            hint="(sheet music source)")

        self._sf2_tc = file_row(
            "Soundfont (.sf2):",
            "Soundfont files (*.sf2)|*.sf2|All files (*.*)|*.*",
            _default("soundfonts/GeneralUser-GS.sf2"),
            hint="(instrument samples for audio)")

        _default_lily = r"C:\Program Files\lilypond-2.24.4\bin\lilypond.exe"
        self._lilypond_tc = file_row(
            "LilyPond binary:",
            "Executables (*.exe)|*.exe|All files (*.*)|*.*",
            _default_lily if Path(_default_lily).exists() else "",
            hint="(blank = use system PATH)")

        self._ffmpeg_tc = file_row(
            "ffmpeg binary:",
            "Executables (*.exe)|*.exe|All files (*.*)|*.*",
            _default("bin/ffmpeg.exe"),
            hint="(blank = use system PATH)")

        self._fluidsynth_tc = file_row(
            "fluidsynth binary:",
            "Executables (*.exe)|*.exe|All files (*.*)|*.*",
            _default("bin/fluidsynth/fluidsynth.exe"),
            hint="(blank = use system PATH)")

        self._dir_tc = dir_row(
            "Output folder:",
            str(HERE / "output"),
            hint="(where to save the MP4)")

        # --- numeric rows ---

        grid.Add(wx.StaticText(panel, label="Resolution (W × H):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._width_ctrl  = wx.SpinCtrl(panel, min=320, max=7680, initial=DEFAULT_WIDTH,  size=(90, -1), name="Video width")
        self._height_ctrl = wx.SpinCtrl(panel, min=240, max=4320, initial=DEFAULT_HEIGHT, size=(90, -1), name="Video height")
        res_box = wx.BoxSizer(wx.HORIZONTAL)
        res_box.Add(self._width_ctrl)
        res_box.Add(wx.StaticText(panel, label=" × "), 0, wx.ALIGN_CENTER_VERTICAL)
        res_box.Add(self._height_ctrl)
        grid.Add(res_box)
        grid.AddSpacer(0)

        grid.Add(wx.StaticText(panel, label="Frame rate (fps):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._fps_ctrl = wx.SpinCtrl(panel, min=15, max=60, initial=DEFAULT_FPS, size=(90, -1), name="Frame rate")
        grid.Add(self._fps_ctrl)
        grid.AddSpacer(0)

        self._tempo_tc = spin_double_row(
            "Tempo multiplier:", 0.25, 4.0, 1.0, 0.05, 2,
            hint="(1.0 = original speed)")

        # --- overlay / option checkboxes ---

        self._fill_height_chk = chk_row(
            "Fit to height:", "Pad strip to output height (centres content, white background)")

        self._cursor_chk = chk_row(
            "Playback cursor:", "Show vertical cursor line")
        self._cursor_chk.SetValue(True)
        self._cursor_color_cp = color_row(
            "Cursor color:", (220, 50, 50))
        grid.Add(wx.StaticText(panel, label="Cursor width (px):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._cursor_width_ctrl = wx.SpinCtrl(panel, min=1, max=8, initial=2, size=(60, -1), name="Cursor width")
        grid.Add(self._cursor_width_ctrl)
        grid.AddSpacer(0)

        self._note_highlight_chk = chk_row(
            "Note highlight:", "Flash active note/chord")
        self._note_highlight_chk.SetValue(True)
        self._highlight_color_cp = color_row(
            "Highlight color:", (50, 120, 220))

        self._trail_chk = chk_row(
            "Note trail:", "Show fading dot trail + played-region tint")
        self._trail_chk.SetValue(True)
        self._title_overlay_chk = chk_row(
            "Title overlay:", "Show title / composer (fixed, does not scroll)",
            hint=r"(from \header in .ly)")
        self._footer_overlay_chk = chk_row(
            "Footer overlay:", "Show copyright / tagline (fixed, does not scroll)",
            hint=r"(from \header in .ly)")
        self._bar_timing_chk = chk_row(
            "Bar timing:", "Scroll one step per bar (smoother for fast passages)")
        self._bar_timing_chk.SetValue(True)
        self._bar_numbers_chk = chk_row(
            "Bar numbers:", "Show bar number above every bar line")
        self._bar_numbers_chk.SetValue(True)
        # Metronome: checkbox + Settings… button
        grid.Add(wx.StaticText(panel, label="Metronome click:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._metronome_chk = wx.CheckBox(
            panel, label="Mix synthesized click track into audio",
            name="Metronome click enabled")
        grid.Add(self._metronome_chk, 0, wx.ALIGN_CENTER_VERTICAL)
        _btn_metro = wx.Button(panel, label="Click settings…", size=(110, -1),
                               name="Click settings")
        _btn_metro.Bind(wx.EVT_BUTTON, self._on_metronome_settings)
        grid.Add(_btn_metro, 0)

        # Watermark: summary label + Settings… button
        grid.Add(wx.StaticText(panel, label="Watermark:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._watermark_summary = wx.StaticText(panel, label="(none)")
        grid.Add(self._watermark_summary, 0, wx.ALIGN_CENTER_VERTICAL)
        _btn_wm = wx.Button(panel, label="Branding settings…", size=(130, -1),
                            name="Branding settings")
        _btn_wm.Bind(wx.EVT_BUTTON, self._on_watermark_settings)
        grid.Add(_btn_wm, 0)

        grid.Add(wx.StaticText(panel, label="Fade in/out (frames):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._fade_frames_ctrl = wx.SpinCtrl(panel, min=0, max=120, initial=0, size=(60, -1),
                                             name="Fade frames")
        grid.Add(self._fade_frames_ctrl)
        grid.Add(wx.StaticText(panel, label="(0 = no fade, 15 = 0.5s at 30fps)"), 0, wx.ALIGN_CENTER_VERTICAL)

        root.Add(grid, 0, wx.EXPAND | wx.ALL, 10)

        # Action buttons
        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_mp4 = wx.Button(panel, label="Encode MP4")
        self._btn_html = wx.Button(panel, label="Generate HTML")
        self._btn_html.Disable()
        self._btn_html.SetToolTip("HTML preview not yet implemented.")
        btn_box.Add(self._btn_mp4, 0, wx.RIGHT, 8)
        btn_box.Add(self._btn_html)
        root.Add(btn_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Log
        root.Add(wx.StaticText(panel, label="Log:"), 0, wx.LEFT, 10)
        self._log = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP | wx.HSCROLL,
            name="Pipeline output log",
        )
        self._log.SetFont(
            wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        )
        root.Add(self._log, 1, wx.EXPAND | wx.ALL, 10)

        # Post-completion buttons
        post_box = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_open_html = wx.Button(panel, label="Open HTML")
        self._btn_explorer = wx.Button(panel, label="Show in Explorer")
        self._btn_open_html.Disable()
        self._btn_explorer.Disable()
        post_box.Add(self._btn_open_html, 0, wx.RIGHT, 8)
        post_box.Add(self._btn_explorer)
        root.Add(post_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        panel.SetSizer(root)

        self._btn_mp4.Bind(wx.EVT_BUTTON, self._on_encode_mp4)
        self._btn_open_html.Bind(wx.EVT_BUTTON, self._on_open_html)
        self._btn_explorer.Bind(wx.EVT_BUTTON, self._on_show_explorer)

    # ------------------------------------------------------------------
    # Log helpers
    # ------------------------------------------------------------------

    def _log_newline(self, text: str) -> None:
        if self._overwriting_log_line:
            self._log.AppendText("\n")
        self._log.AppendText(text + "\n")
        self._overwriting_log_line = False

    def _log_overwrite(self, text: str) -> None:
        if self._overwriting_log_line:
            pos = self._log.GetLastPosition()
            content = self._log.GetValue()
            last_nl = content.rfind("\n")
            start = last_nl + 1 if last_nl >= 0 else 0
            self._log.Remove(start, pos)
        self._log.AppendText(text)
        self._overwriting_log_line = True

    # ------------------------------------------------------------------
    # Encode MP4
    # ------------------------------------------------------------------

    def _on_encode_mp4(self, _event) -> None:
        ly = self._ly_tc.GetValue().strip()
        sf2 = self._sf2_tc.GetValue().strip()
        out_dir = self._dir_tc.GetValue().strip()

        if not ly or not Path(ly).is_file():
            wx.MessageBox("Select a valid .ly file.", "Input required", wx.ICON_WARNING)
            return
        if not sf2 or not Path(sf2).is_file():
            wx.MessageBox("Select a valid .sf2 soundfont.", "Input required", wx.ICON_WARNING)
            return
        if not out_dir:
            wx.MessageBox("Select an output folder.", "Input required", wx.ICON_WARNING)
            return

        width = self._width_ctrl.GetValue()
        height = self._height_ctrl.GetValue()
        if width % 2 != 0 or height % 2 != 0:
            wx.MessageBox(
                "Width and height must both be even numbers (ffmpeg requirement).",
                "Invalid resolution", wx.ICON_WARNING,
            )
            return

        try:
            tempo = float(self._tempo_tc.GetValue())
        except ValueError:
            tempo = 1.0

        out_mp4 = str(Path(out_dir) / f"{Path(ly).stem}.mp4")
        self._mp4_path = out_mp4

        fps = self._fps_ctrl.GetValue()
        cursor_line = self._cursor_chk.GetValue()
        cursor_color = _parse_color(self._cursor_color_cp, (220, 50, 50))
        cursor_width = self._cursor_width_ctrl.GetValue()
        note_highlight = self._note_highlight_chk.GetValue()
        highlight_color = _parse_color(self._highlight_color_cp, (50, 120, 220))
        trail = self._trail_chk.GetValue()
        overlay_title = self._title_overlay_chk.GetValue()
        overlay_footer = self._footer_overlay_chk.GetValue()
        use_bar_timing = self._bar_timing_chk.GetValue()
        bar_numbers = self._bar_numbers_chk.GetValue()
        metronome = self._metronome_chk.GetValue()
        click_a = self._click_a
        click_b = self._click_b
        count_in_bars = self._count_in
        fade_frames = self._fade_frames_ctrl.GetValue()
        watermark = self._watermark
        fill_height = self._fill_height_chk.GetValue()
        lilypond_exe = self._lilypond_tc.GetValue().strip() or None
        ffmpeg_exe = self._ffmpeg_tc.GetValue().strip() or None
        fluidsynth_exe = self._fluidsynth_tc.GetValue().strip() or None

        config = PipelineConfig(
            ly=ly, sf2=sf2, out_mp4=out_mp4,
            width=width, height=height, fps=fps, tempo=tempo,
            cursor_line=cursor_line, cursor_color=cursor_color, cursor_width=cursor_width,
            note_highlight=note_highlight, highlight_color=highlight_color,
            trail=trail, overlay_title=overlay_title, overlay_footer=overlay_footer,
            use_bar_timing=use_bar_timing, bar_numbers=bar_numbers,
            metronome=metronome, click_a=click_a, click_b=click_b,
            count_in_bars=count_in_bars, fade_frames=fade_frames,
            watermark=watermark, fill_height=fill_height,
            lilypond_exe=lilypond_exe, ffmpeg_exe=ffmpeg_exe, fluidsynth_exe=fluidsynth_exe,
        )

        self._log.Clear()
        self._overwriting_log_line = False
        self._btn_mp4.Disable()
        self._btn_explorer.Disable()
        self.SetStatusText("Encoding…")

        stream = _LogStream(self._log_newline, self._log_overwrite)
        threading.Thread(
            target=self._run_pipeline,
            args=(config, stream),
            daemon=True,
        ).start()

    def _on_metronome_settings(self, _event) -> None:
        dlg = MetronomeDialog(self, self._click_a, self._click_b, self._count_in)
        if dlg.ShowModal() == wx.ID_OK:
            self._click_a, self._click_b, self._count_in = dlg.get_values()
        dlg.Destroy()

    def _on_watermark_settings(self, _event) -> None:
        dlg = WatermarkDialog(self, self._watermark)
        if dlg.ShowModal() == wx.ID_OK:
            self._watermark = dlg.get_values()
            name = Path(self._watermark.path).name if self._watermark.path else "(none)"
            self._watermark_summary.SetLabel(name)
        dlg.Destroy()

    def _run_pipeline(self, config: PipelineConfig, stream) -> None:
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = stream
        sys.stderr = stream
        try:
            generate_mp4(
                ly_path=config.ly,
                sf2_path=config.sf2,
                out_path=config.out_mp4,
                width=config.width,
                height=config.height,
                fps=config.fps,
                tempo_multiplier=config.tempo,
                lilypond_exe=config.lilypond_exe,
                ffmpeg_exe=config.ffmpeg_exe,
                fluidsynth_exe=config.fluidsynth_exe,
                cursor_line=config.cursor_line,
                cursor_color=config.cursor_color,
                cursor_width=config.cursor_width,
                trail=config.trail,
                note_highlight=config.note_highlight,
                highlight_color=config.highlight_color,
                overlay_title=config.overlay_title,
                overlay_footer=config.overlay_footer,
                use_bar_timing=config.use_bar_timing,
                bar_numbers=config.bar_numbers,
                metronome=config.metronome,
                click_accent=config.click_a,
                click_beat=config.click_b,
                count_in_bars=config.count_in_bars,
                fade_frames=config.fade_frames,
                watermark=config.watermark,
                fill_height=config.fill_height,
            )
            wx.CallAfter(self._pipeline_done, success=True, path=config.out_mp4)
        except Exception as exc:
            wx.CallAfter(self._log_newline, f"\nERROR: {exc}")
            wx.CallAfter(self._pipeline_done, success=False, path=config.out_mp4)
        finally:
            sys.stdout = old_out
            sys.stderr = old_err

    def _pipeline_done(self, success: bool, path: str) -> None:
        self._btn_mp4.Enable()
        if success:
            self._log_newline(f"\nDone: {path}")
            self._btn_explorer.Enable()
            self.SetStatusText(f"Done: {Path(path).name}")
        else:
            self._log_newline("\nEncoding failed. See log above.")
            self.SetStatusText("Encoding failed.")

    # ------------------------------------------------------------------
    # Post-completion
    # ------------------------------------------------------------------

    def _on_open_html(self, _event) -> None:
        if self._html_path and Path(self._html_path).is_file():
            webbrowser.open(self._html_path)

    def _on_show_explorer(self, _event) -> None:
        if self._mp4_path and Path(self._mp4_path).is_file():
            subprocess.Popen(["explorer", "/select,", self._mp4_path])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    app = wx.App()
    MainFrame()
    app.MainLoop()


if __name__ == "__main__":
    main()
