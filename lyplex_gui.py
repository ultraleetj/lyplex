"""
lyplex_gui.py — accessible wxPython GUI for LyPlex pipeline
Run: python lyplex_gui.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import wx

from lyplex_tool import DEFAULT_FPS, DEFAULT_HEIGHT, DEFAULT_WIDTH, ClickParams, WatermarkParams, generate_mp4, _extract_source_bpm
from lyplex_strings import STRINGS
from lyplex_help import HELP

HERE = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent

# ---------------------------------------------------------------------------
# i18n helpers
# ---------------------------------------------------------------------------

_lang: str = "en"

def S(key: str, **kwargs) -> str:
    """Return the string for key in the current language, with optional format args."""
    s = STRINGS[_lang].get(key) or STRINGS["en"].get(key, key)
    return s.format(**kwargs) if kwargs else s

# ---------------------------------------------------------------------------
# Color presets — keys reference STRINGS for translated names
# ---------------------------------------------------------------------------

_COLOR_PRESET_DATA: list[tuple[str, tuple[int, int, int]]] = [
    ("color_red",    (220,  50,  50)),
    ("color_blue",   ( 50, 120, 220)),
    ("color_green",  ( 50, 180,  80)),
    ("color_yellow", (240, 200,  30)),
    ("color_cyan",   ( 40, 200, 220)),
    ("color_orange", (240, 130,  40)),
    ("color_white",  (255, 255, 255)),
    ("color_black",  (  0,   0,   0)),
    ("color_purple", (160,  60, 200)),
    ("color_pink",   (240, 100, 160)),
]

def _color_names() -> list[str]:
    return [S(key) for key, _ in _COLOR_PRESET_DATA]

def _parse_color(choice: wx.Choice, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    i = choice.GetSelection()
    return _COLOR_PRESET_DATA[i][1] if 0 <= i < len(_COLOR_PRESET_DATA) else fallback

def _default_color_idx(rgb: tuple[int, int, int]) -> int:
    return next((i for i, (_, r) in enumerate(_COLOR_PRESET_DATA) if r == rgb), 0)


def _default(rel: str) -> str:
    p = HERE / rel
    return str(p) if p.exists() else ""


def _spin_double(parent: wx.Window, lo: float, hi: float, val: float, inc: float, name: str) -> wx.SpinCtrlDouble:
    c = wx.SpinCtrlDouble(parent, min=lo, max=hi, initial=val, inc=inc, name=name)
    c.SetDigits(2)
    return c


# ---------------------------------------------------------------------------
# PipelineConfig
# ---------------------------------------------------------------------------

@dataclass
class PipelineConfig:
    ly: str
    sf2: str
    out_mp4: str
    width: int
    height: int
    fps: int
    tempo_bpm: float | None
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
    volume_db: float
    click_volume_db: float
    lilypond_exe: str | None
    ffmpeg_exe: str | None
    fluidsynth_exe: str | None


# ---------------------------------------------------------------------------
# HelpDialog
# ---------------------------------------------------------------------------

class HelpDialog(wx.Dialog):
    def __init__(self, parent):
        data = HELP[_lang]
        super().__init__(parent, title=data["title"],
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
                         size=(620, 520))
        panel = wx.Panel(self)

        tc = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP,
        )
        tc.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))

        text_parts: list[str] = []
        for section in data["sections"]:
            heading = section["heading"]
            text_parts.append(heading)
            text_parts.append("─" * 48)
            text_parts.append(section["body"])
            text_parts.append("")
        tc.SetValue("\n".join(text_parts))

        close_btn = wx.Button(panel, wx.ID_CLOSE)
        close_btn.Bind(wx.EVT_BUTTON, lambda _e: self.EndModal(wx.ID_CLOSE))
        self.Bind(wx.EVT_CHAR_HOOK, lambda e: self.EndModal(wx.ID_CLOSE) if e.GetKeyCode() == wx.WXK_ESCAPE else e.Skip())

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(tc, 1, wx.EXPAND | wx.ALL, 10)
        sizer.Add(close_btn, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        panel.SetSizer(sizer)
        self.Centre()


# ---------------------------------------------------------------------------
# MetronomeDialog
# ---------------------------------------------------------------------------

_WAVEFORMS: list[tuple[str, str]] = [
    ("sine",     "waveform_sine"),
    ("square",   "waveform_square"),
    ("triangle", "waveform_triangle"),
    ("saw",      "waveform_saw"),
]

_T = TypeVar("_T", bound=wx.Window)

class MetronomeDialog(wx.Dialog):

    def __init__(self, parent, click_a: ClickParams, click_b: ClickParams, count_in: int,
                 click_volume_db: float = -3.0):
        super().__init__(parent, title=S("metro_dialog_title"),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        panel = wx.Panel(self)
        grid = wx.FlexGridSizer(cols=3, hgap=8, vgap=6)
        grid.AddGrowableCol(1, 1)

        def _section(key: str) -> None:
            st = wx.StaticText(panel, label=S(key))
            st.SetFont(st.GetFont().Bold())
            grid.Add(st, 0, wx.TOP | wx.ALIGN_CENTER_VERTICAL, 6)
            grid.AddSpacer(0)
            grid.AddSpacer(0)

        def _row(label_key: str, ctrl, hint_key: str = "") -> None:
            grid.Add(wx.StaticText(panel, label=S(label_key)), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(ctrl, 0, wx.EXPAND)
            grid.Add(wx.StaticText(panel, label=S(hint_key)) if hint_key else (0, 0),
                     0, wx.ALIGN_CENTER_VERTICAL)

        wf_labels = [S(k) for _, k in _WAVEFORMS]

        def _wf_idx(p: ClickParams) -> int:
            return next((i for i, (v, _) in enumerate(_WAVEFORMS) if v == p.waveform), 0)

        _section("metro_section_accent")
        self._a_freq = wx.SpinCtrl(panel, min=100, max=8000, initial=int(click_a.freq_hz))
        _row("metro_label_frequency", self._a_freq, "metro_hint_frequency")
        self._a_wave = wx.Choice(panel, choices=wf_labels)
        self._a_wave.SetSelection(_wf_idx(click_a))
        _row("metro_label_waveform", self._a_wave)
        self._a_dur = wx.SpinCtrl(panel, min=5, max=200, initial=int(click_a.duration_ms))
        _row("metro_label_duration", self._a_dur, "metro_hint_duration")
        self._a_amp = _spin_double(panel, 0.05, 1.0, click_a.amplitude, 0.05, "")
        _row("metro_label_amplitude", self._a_amp, "metro_hint_amplitude")

        _section("metro_section_beat")
        self._b_freq = wx.SpinCtrl(panel, min=100, max=8000, initial=int(click_b.freq_hz))
        _row("metro_label_frequency", self._b_freq, "metro_hint_frequency")
        self._b_wave = wx.Choice(panel, choices=wf_labels)
        self._b_wave.SetSelection(_wf_idx(click_b))
        _row("metro_label_waveform", self._b_wave)
        self._b_dur = wx.SpinCtrl(panel, min=5, max=200, initial=int(click_b.duration_ms))
        _row("metro_label_duration", self._b_dur, "metro_hint_duration")
        self._b_amp = _spin_double(panel, 0.05, 1.0, click_b.amplitude, 0.05, "")
        _row("metro_label_amplitude", self._b_amp, "metro_hint_amplitude")

        _section("metro_section_count_in")
        self._count_in_spin = wx.SpinCtrl(panel, min=0, max=4, initial=count_in)
        _row("metro_label_bars", self._count_in_spin, "metro_hint_count_in_bars")

        _section("metro_section_mix")
        self._click_vol = _spin_double(panel, -24.0, 12.0, click_volume_db, 0.5, "")
        _row("metro_label_click_volume", self._click_vol, "metro_hint_click_volume")

        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(grid, 0, wx.EXPAND | wx.ALL, 12)
        root.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        root.Add(btns, 0, wx.EXPAND | wx.ALL, 8)
        panel.SetSizer(root)
        root.Fit(self)

    def get_values(self) -> tuple[ClickParams, ClickParams, int, float]:
        def _wf(choice: wx.Choice) -> str:
            i = choice.GetSelection()
            return _WAVEFORMS[i][0] if 0 <= i < len(_WAVEFORMS) else "sine"
        a = ClickParams(
            freq_hz=float(self._a_freq.GetValue()),
            waveform=_wf(self._a_wave),
            duration_ms=float(self._a_dur.GetValue()),
            amplitude=self._a_amp.GetValue(),
        )
        b = ClickParams(
            freq_hz=float(self._b_freq.GetValue()),
            waveform=_wf(self._b_wave),
            duration_ms=float(self._b_dur.GetValue()),
            amplitude=self._b_amp.GetValue(),
        )
        return a, b, self._count_in_spin.GetValue(), self._click_vol.GetValue()


# ---------------------------------------------------------------------------
# WatermarkDialog
# ---------------------------------------------------------------------------

class WatermarkDialog(wx.Dialog):
    _POSITIONS = ["BR", "BL", "TR", "TL"]

    def __init__(self, parent, params: WatermarkParams):
        super().__init__(parent, title=S("wm_dialog_title"),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        panel = wx.Panel(self)
        grid = wx.FlexGridSizer(cols=3, hgap=8, vgap=8)
        grid.AddGrowableCol(1, 1)

        grid.Add(wx.StaticText(panel, label=S("wm_label_logo")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._path_tc = wx.TextCtrl(panel, value=params.path)
        btn_browse = wx.Button(panel, label=S("btn_browse"), size=(80, -1))
        def _on_browse(_e):
            dlg = wx.FileDialog(self, message=S("dlg_open_file"),
                                wildcard=S("wildcard_images"),
                                style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
            if dlg.ShowModal() == wx.ID_OK:
                self._path_tc.SetValue(dlg.GetPath())
            dlg.Destroy()
        btn_browse.Bind(wx.EVT_BUTTON, _on_browse)
        sz_path = wx.BoxSizer(wx.HORIZONTAL)
        sz_path.Add(self._path_tc, 1, wx.EXPAND)
        sz_path.Add(btn_browse, 0, wx.LEFT, 4)
        grid.Add(sz_path, 1, wx.EXPAND)
        grid.Add(wx.StaticText(panel, label=S("wm_hint_logo")), 0, wx.ALIGN_CENTER_VERTICAL)

        pos_idx = next((i for i, p in enumerate(self._POSITIONS) if p == params.position), 0)
        grid.Add(wx.StaticText(panel, label=S("wm_label_position")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._pos_ch = wx.Choice(panel, choices=self._POSITIONS)
        self._pos_ch.SetSelection(pos_idx)
        grid.Add(self._pos_ch, 0)
        grid.Add(wx.StaticText(panel, label=S("wm_hint_position")), 0, wx.ALIGN_CENTER_VERTICAL)

        grid.Add(wx.StaticText(panel, label=S("wm_label_opacity")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._opacity_ctrl = _spin_double(panel, 0.05, 1.0, params.opacity, 0.05, "")
        grid.Add(self._opacity_ctrl, 0)
        grid.Add(wx.StaticText(panel, label=S("wm_hint_opacity")), 0, wx.ALIGN_CENTER_VERTICAL)

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
# Log stream
# ---------------------------------------------------------------------------

class _LogStream:
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
        super().__init__(None, title=S("window_title"), size=(760, 960))
        self._mp4_path: str | None = None
        self._overwriting_log_line = False
        self._last_line_start = 0
        self._bpm_timer: wx.CallLater | None = None
        self._cancel_event: threading.Event | None = None
        self._click_a = ClickParams(freq_hz=1500.0, waveform="sine", duration_ms=20.0, amplitude=0.6)
        self._click_b = ClickParams(freq_hz=1000.0, waveform="sine", duration_ms=20.0, amplitude=0.4)
        self._count_in = 0
        self._click_volume_db = -3.0
        self._watermark = WatermarkParams()
        # i18n tracking: (widget, string_key, setter_method) — SetLabel or SetName
        self._i18n: list[tuple[wx.Window, str, str]] = []
        self._color_choices: list[wx.Choice] = []
        self._build_ui()
        self.CreateStatusBar()
        self.SetStatusText(S("status_ready"))
        self.Centre()
        self.Show()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)

        grid = wx.FlexGridSizer(cols=3, hgap=6, vgap=8)
        grid.AddGrowableCol(1, 1)

        # ---- i18n tracking helpers ----
        def _t(w: _T, key: str) -> _T:
            self._i18n.append((w, key, "SetLabel"))
            return w

        def _tn(w: _T, key: str) -> _T:
            """Track a widget for SetName updates (accessibility labels)."""
            self._i18n.append((w, key, "SetName"))
            return w

        # ---- row builder helpers ----

        def _picker_row(label_key: str, make_dialog, default: str = "",
                        hint_key: str = "") -> wx.TextCtrl:
            grid.Add(_t(wx.StaticText(panel, label=S(label_key)), label_key),
                     0, wx.ALIGN_CENTER_VERTICAL)
            tc  = wx.TextCtrl(panel, value=default)
            btn = _t(wx.Button(panel, label=S("btn_browse"), size=(80, -1)), "btn_browse")
            def on_browse(_e, _tc=tc):
                dlg = make_dialog()
                if dlg.ShowModal() == wx.ID_OK:
                    _tc.SetValue(dlg.GetPath())
                dlg.Destroy()
            btn.Bind(wx.EVT_BUTTON, on_browse)
            sz = wx.BoxSizer(wx.HORIZONTAL)
            sz.Add(tc, 1, wx.EXPAND)
            sz.Add(btn, 0, wx.LEFT, 4)
            grid.Add(sz, 1, wx.EXPAND)
            if hint_key:
                grid.Add(_t(wx.StaticText(panel, label=S(hint_key)), hint_key),
                         0, wx.ALIGN_CENTER_VERTICAL)
            else:
                grid.AddSpacer(0)
            return tc

        def file_row(label_key: str, wildcard_key: str, default: str = "",
                     hint_key: str = "") -> wx.TextCtrl:
            return _picker_row(
                label_key,
                lambda wk=wildcard_key: wx.FileDialog(
                    self, message=S("dlg_open_file"),
                    wildcard=S(wk), style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST),
                default, hint_key)

        def dir_row(label_key: str, default: str = "", hint_key: str = "") -> wx.TextCtrl:
            return _picker_row(
                label_key,
                lambda: wx.DirDialog(self, message=S("dlg_open_folder")),
                default, hint_key)

        def spin_double_row(label_key: str, min_v: float, max_v: float,
                            initial: float, inc: float, digits: int,
                            hint_key: str = "") -> wx.TextCtrl:
            grid.Add(_t(wx.StaticText(panel, label=S(label_key)), label_key),
                     0, wx.ALIGN_CENTER_VERTICAL)
            tc = wx.TextCtrl(panel, value=f"{initial:.{digits}f}", size=(80, -1))
            sp = wx.SpinButton(panel, style=wx.SP_VERTICAL)
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
            grid.Add(sz, 0)
            if hint_key:
                grid.Add(_t(wx.StaticText(panel, label=S(hint_key)), hint_key),
                         0, wx.ALIGN_CENTER_VERTICAL)
            else:
                grid.AddSpacer(0)
            return tc

        def chk_row(label_key: str, chk_key: str, hint_key: str = "") -> wx.CheckBox:
            grid.Add(_t(wx.StaticText(panel, label=S(label_key)), label_key),
                     0, wx.ALIGN_CENTER_VERTICAL)
            chk = _t(wx.CheckBox(panel, label=S(chk_key)), chk_key)
            grid.Add(chk, 0)
            if hint_key:
                grid.Add(_t(wx.StaticText(panel, label=S(hint_key)), hint_key),
                         0, wx.ALIGN_CENTER_VERTICAL)
            else:
                grid.AddSpacer(0)
            return chk

        def color_row(label_key: str, default_rgb: tuple,
                      hint_key: str = "") -> wx.Choice:
            grid.Add(_t(wx.StaticText(panel, label=S(label_key)), label_key),
                     0, wx.ALIGN_CENTER_VERTICAL)
            ch = wx.Choice(panel, choices=_color_names())
            ch.SetSelection(_default_color_idx(default_rgb))
            self._color_choices.append(ch)
            swatch = wx.Panel(panel, size=(20, 20))
            swatch.SetBackgroundColour(wx.Colour(*default_rgb))
            def _update_swatch(_e, _ch=ch, _sw=swatch):
                i = _ch.GetSelection()
                if 0 <= i < len(_COLOR_PRESET_DATA):
                    _sw.SetBackgroundColour(wx.Colour(*_COLOR_PRESET_DATA[i][1]))
                    _sw.Refresh()
            ch.Bind(wx.EVT_CHOICE, _update_swatch)
            sz = wx.BoxSizer(wx.HORIZONTAL)
            sz.Add(ch, 0, wx.ALIGN_CENTER_VERTICAL)
            sz.Add(swatch, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 4)
            grid.Add(sz, 0)
            if hint_key:
                grid.Add(_t(wx.StaticText(panel, label=S(hint_key)), hint_key),
                         0, wx.ALIGN_CENTER_VERTICAL)
            else:
                grid.AddSpacer(0)
            return ch

        # --- file / folder rows ---

        self._ly_tc = file_row("label_ly_file", "wildcard_ly", hint_key="hint_ly_file")
        self._ly_tc.Bind(wx.EVT_TEXT, self._on_ly_changed)

        self._sf2_tc = file_row("label_sf2", "wildcard_sf2",
                                _default("soundfonts/GeneralUser-GS.sf2"),
                                hint_key="hint_sf2")

        _default_lily = r"C:\Program Files\lilypond-2.24.4\bin\lilypond.exe"
        self._lilypond_tc = file_row("label_lilypond_bin", "wildcard_exe",
                                     _default_lily if Path(_default_lily).exists() else "",
                                     hint_key="hint_lilypond_bin")

        self._ffmpeg_tc = file_row("label_ffmpeg_bin", "wildcard_exe",
                                   _default("bin/ffmpeg.exe"),
                                   hint_key="hint_ffmpeg_bin")

        self._fluidsynth_tc = file_row("label_fluidsynth_bin", "wildcard_exe",
                                       _default("bin/fluidsynth/fluidsynth.exe"),
                                       hint_key="hint_fluidsynth_bin")

        self._dir_tc = dir_row("label_output_folder", str(HERE / "output"),
                               hint_key="hint_output_folder")

        # --- resolution ---
        grid.Add(_t(wx.StaticText(panel, label=S("label_resolution")), "label_resolution"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._width_ctrl  = _tn(wx.SpinCtrl(panel, min=320, max=7680, initial=DEFAULT_WIDTH,
                                        size=(90, -1), name=S("accessible_video_width")),
                                "accessible_video_width")
        self._height_ctrl = _tn(wx.SpinCtrl(panel, min=240, max=4320, initial=DEFAULT_HEIGHT,
                                        size=(90, -1), name=S("accessible_video_height")),
                                "accessible_video_height")
        self._res_x_lbl = _t(wx.StaticText(panel, label=S("label_resolution_x")), "label_resolution_x")
        res_box = wx.BoxSizer(wx.HORIZONTAL)
        res_box.Add(self._width_ctrl)
        res_box.Add(self._res_x_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        res_box.Add(self._height_ctrl)
        grid.Add(res_box)
        grid.AddSpacer(0)

        # --- fps ---
        grid.Add(_t(wx.StaticText(panel, label=S("label_frame_rate")), "label_frame_rate"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._fps_ctrl = _tn(wx.SpinCtrl(panel, min=15, max=60, initial=DEFAULT_FPS,
                                     size=(90, -1), name=S("accessible_frame_rate")),
                             "accessible_frame_rate")
        grid.Add(self._fps_ctrl)
        grid.AddSpacer(0)

        self._tempo_tc = spin_double_row("label_target_bpm", 20.0, 400.0, 0.0, 1.0, 0,
                                        hint_key="hint_target_bpm")

        # --- overlays ---
        self._fill_height_chk = chk_row("label_fit_to_height", "chk_fit_to_height")

        self._cursor_chk = chk_row("label_playback_cursor", "chk_playback_cursor")
        self._cursor_chk.SetValue(True)
        self._cursor_color_cp = color_row("label_cursor_color", (220, 50, 50))

        grid.Add(_t(wx.StaticText(panel, label=S("label_cursor_width")), "label_cursor_width"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._cursor_width_ctrl = _tn(wx.SpinCtrl(panel, min=1, max=8, initial=2,
                                              size=(60, -1), name=S("accessible_cursor_width")),
                                      "accessible_cursor_width")
        grid.Add(self._cursor_width_ctrl)
        grid.AddSpacer(0)

        self._note_highlight_chk = chk_row("label_note_highlight", "chk_note_highlight")
        self._note_highlight_chk.SetValue(True)
        self._highlight_color_cp = color_row("label_highlight_color", (50, 120, 220))

        self._trail_chk = chk_row("label_note_trail", "chk_note_trail")
        self._trail_chk.SetValue(True)

        self._title_overlay_chk = chk_row("label_title_overlay", "chk_title_overlay",
                                          hint_key="hint_title_overlay")
        self._title_overlay_chk.SetValue(True)

        self._footer_overlay_chk = chk_row("label_footer_overlay", "chk_footer_overlay",
                                           hint_key="hint_footer_overlay")

        self._bar_timing_chk = chk_row("label_bar_timing", "chk_bar_timing")
        self._bar_timing_chk.SetValue(True)

        self._bar_numbers_chk = chk_row("label_bar_numbers", "chk_bar_numbers")
        self._bar_numbers_chk.SetValue(True)

        # --- metronome ---
        grid.Add(_t(wx.StaticText(panel, label=S("label_metronome")), "label_metronome"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._metronome_chk = _t(
            _tn(wx.CheckBox(panel, label=S("chk_metronome"), name=S("accessible_metronome")),
                "accessible_metronome"),
            "chk_metronome")
        grid.Add(self._metronome_chk, 0, wx.ALIGN_CENTER_VERTICAL)
        self._btn_metro = _t(
            wx.Button(panel, label=S("btn_click_settings"), size=(130, -1)),
            "btn_click_settings")
        self._btn_metro.Bind(wx.EVT_BUTTON, self._on_metronome_settings)
        grid.Add(self._btn_metro, 0)

        # --- watermark ---
        grid.Add(_t(wx.StaticText(panel, label=S("label_watermark")), "label_watermark"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._watermark_summary = wx.StaticText(panel, label=S("watermark_none"))
        grid.Add(self._watermark_summary, 0, wx.ALIGN_CENTER_VERTICAL)
        self._btn_wm = _t(
            wx.Button(panel, label=S("btn_branding_settings"), size=(140, -1)),
            "btn_branding_settings")
        self._btn_wm.Bind(wx.EVT_BUTTON, self._on_watermark_settings)
        grid.Add(self._btn_wm, 0)

        # --- fade / volume ---
        grid.Add(_t(wx.StaticText(panel, label=S("label_fade_frames")), "label_fade_frames"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._fade_frames_ctrl = _tn(wx.SpinCtrl(panel, min=0, max=120, initial=0,
                                             size=(60, -1), name=S("accessible_fade_frames")),
                                     "accessible_fade_frames")
        grid.Add(self._fade_frames_ctrl)
        grid.Add(_t(wx.StaticText(panel, label=S("hint_fade_frames")), "hint_fade_frames"),
                 0, wx.ALIGN_CENTER_VERTICAL)

        grid.Add(_t(wx.StaticText(panel, label=S("label_music_volume")), "label_music_volume"),
                 0, wx.ALIGN_CENTER_VERTICAL)
        self._volume_db_ctrl = _tn(
            _spin_double(panel, -12.0, 30.0, 14.5, 0.5, S("accessible_music_volume")),
            "accessible_music_volume")
        grid.Add(self._volume_db_ctrl)
        grid.Add(_t(wx.StaticText(panel, label=S("hint_music_volume")), "hint_music_volume"),
                 0, wx.ALIGN_CENTER_VERTICAL)

        self._auto_open_chk = chk_row("label_auto_open", "chk_auto_open")

        root.Add(grid, 0, wx.EXPAND | wx.ALL, 10)

        # --- action buttons ---
        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_mp4    = _t(wx.Button(panel, label=S("btn_encode_mp4")), "btn_encode_mp4")
        self._btn_cancel = _t(wx.Button(panel, label=S("btn_cancel")),     "btn_cancel")
        self._btn_cancel.Disable()
        self._btn_help = _t(wx.Button(panel, label=S("btn_help"), size=(70, -1)), "btn_help")
        # Language toggle shows the OTHER language name
        self._btn_lang = wx.Button(panel, label="Español", size=(80, -1))
        btn_box.Add(self._btn_mp4,    0, wx.RIGHT, 8)
        btn_box.Add(self._btn_cancel, 0, wx.RIGHT, 8)
        btn_box.AddStretchSpacer()
        btn_box.Add(self._btn_help,   0, wx.RIGHT, 8)
        btn_box.Add(self._btn_lang,   0)
        root.Add(btn_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # --- log ---
        root.Add(_t(wx.StaticText(panel, label=S("label_log")), "label_log"), 0, wx.LEFT, 10)
        self._log = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP | wx.HSCROLL,
            name=S("log_accessible_name"),
        )
        self._log.SetFont(
            wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        root.Add(self._log, 1, wx.EXPAND | wx.ALL, 10)

        # --- post-completion buttons ---
        post_box = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_open_mp4    = _t(wx.Button(panel, label=S("btn_open_mp4")),    "btn_open_mp4")
        self._btn_open_folder = _t(wx.Button(panel, label=S("btn_open_folder")), "btn_open_folder")
        self._btn_open_mp4.Disable()
        self._btn_open_folder.Disable()
        post_box.Add(self._btn_open_mp4,    0, wx.RIGHT, 8)
        post_box.Add(self._btn_open_folder, 0)
        root.Add(post_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        panel.SetSizer(root)

        self._btn_mp4.Bind(wx.EVT_BUTTON,    self._on_encode_mp4)
        self._btn_cancel.Bind(wx.EVT_BUTTON, self._on_cancel)
        self._btn_help.Bind(wx.EVT_BUTTON,   self._on_help)
        self._btn_lang.Bind(wx.EVT_BUTTON,   self._on_toggle_lang)
        self._btn_open_mp4.Bind(wx.EVT_BUTTON,    self._on_open_mp4)
        self._btn_open_folder.Bind(wx.EVT_BUTTON, self._on_open_folder)

    # ------------------------------------------------------------------
    # Language switching
    # ------------------------------------------------------------------

    def _on_toggle_lang(self, _event) -> None:
        global _lang
        _lang = "es" if _lang == "en" else "en"
        self._apply_language()

    def _apply_language(self) -> None:
        self.Freeze()
        try:
            for widget, key, method in self._i18n:
                getattr(widget, method)(S(key))
            names = _color_names()
            for ch in self._color_choices:
                sel = ch.GetSelection()
                ch.SetItems(names)
                ch.SetSelection(sel if sel >= 0 else 0)
            if not self._watermark.path:
                self._watermark_summary.SetLabel(S("watermark_none"))
            self.SetTitle(S("window_title"))
            self._btn_lang.SetLabel("English" if _lang == "es" else "Español")
            self.Layout()
        finally:
            self.Thaw()

    # ------------------------------------------------------------------
    # Log helpers
    # ------------------------------------------------------------------

    def _log_newline(self, text: str) -> None:
        if self._overwriting_log_line:
            self._log.AppendText("\n")
        self._log.AppendText(text + "\n")
        self._last_line_start = self._log.GetLastPosition()
        self._overwriting_log_line = False

    def _log_overwrite(self, text: str) -> None:
        if self._overwriting_log_line:
            self._log.Remove(self._last_line_start, self._log.GetLastPosition())
        self._log.AppendText(text)
        self._overwriting_log_line = True

    # ------------------------------------------------------------------
    # BPM auto-detect
    # ------------------------------------------------------------------

    def _on_ly_changed(self, _event) -> None:
        if self._bpm_timer is not None:
            self._bpm_timer.Stop()
        self._bpm_timer = wx.CallLater(400, self._update_bpm_from_ly)

    def _update_bpm_from_ly(self) -> None:
        ly_path = self._ly_tc.GetValue().strip()
        if Path(ly_path).is_file():
            try:
                bpm = _extract_source_bpm(Path(ly_path).read_text(encoding="utf-8"))
                if bpm is not None:
                    self._tempo_tc.SetValue(f"{bpm:.0f}")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Encode MP4
    # ------------------------------------------------------------------

    def _on_encode_mp4(self, _event) -> None:
        ly      = self._ly_tc.GetValue().strip()
        sf2     = self._sf2_tc.GetValue().strip()
        out_dir = self._dir_tc.GetValue().strip()

        if not ly or not Path(ly).is_file():
            wx.MessageBox(S("msg_select_ly"), S("msg_input_required_title"), wx.ICON_WARNING)
            return
        if not sf2 or not Path(sf2).is_file():
            wx.MessageBox(S("msg_select_sf2"), S("msg_input_required_title"), wx.ICON_WARNING)
            return
        if not out_dir:
            wx.MessageBox(S("msg_select_output_folder"), S("msg_input_required_title"), wx.ICON_WARNING)
            return
        Path(out_dir).mkdir(parents=True, exist_ok=True)

        width  = self._width_ctrl.GetValue()
        height = self._height_ctrl.GetValue()
        if width % 2 != 0 or height % 2 != 0:
            wx.MessageBox(S("msg_even_resolution"), S("msg_invalid_res_title"), wx.ICON_WARNING)
            return

        try:
            _bpm_val  = float(self._tempo_tc.GetValue())
            tempo_bpm = _bpm_val if _bpm_val > 0 else None
        except ValueError:
            tempo_bpm = None

        out_mp4 = str(Path(out_dir) / f"{Path(ly).stem}.mp4")
        self._mp4_path = out_mp4

        config = PipelineConfig(
            ly=ly, sf2=sf2, out_mp4=out_mp4,
            width=width, height=height,
            fps=self._fps_ctrl.GetValue(),
            tempo_bpm=tempo_bpm,
            cursor_line=self._cursor_chk.GetValue(),
            cursor_color=_parse_color(self._cursor_color_cp, (220, 50, 50)),
            cursor_width=self._cursor_width_ctrl.GetValue(),
            note_highlight=self._note_highlight_chk.GetValue(),
            highlight_color=_parse_color(self._highlight_color_cp, (50, 120, 220)),
            trail=self._trail_chk.GetValue(),
            overlay_title=self._title_overlay_chk.GetValue(),
            overlay_footer=self._footer_overlay_chk.GetValue(),
            use_bar_timing=self._bar_timing_chk.GetValue(),
            bar_numbers=self._bar_numbers_chk.GetValue(),
            metronome=self._metronome_chk.GetValue(),
            click_a=self._click_a, click_b=self._click_b,
            count_in_bars=self._count_in,
            fade_frames=self._fade_frames_ctrl.GetValue(),
            watermark=self._watermark,
            fill_height=self._fill_height_chk.GetValue(),
            volume_db=self._volume_db_ctrl.GetValue(),
            click_volume_db=self._click_volume_db,
            lilypond_exe=self._lilypond_tc.GetValue().strip() or None,
            ffmpeg_exe=self._ffmpeg_tc.GetValue().strip() or None,
            fluidsynth_exe=self._fluidsynth_tc.GetValue().strip() or None,
        )

        self._log.Clear()
        self._overwriting_log_line = False
        self._btn_mp4.Disable()
        self._btn_open_mp4.Disable()
        self._btn_open_folder.Disable()
        self._cancel_event = threading.Event()
        self._btn_cancel.Enable()
        self.SetStatusText(S("status_encoding"))

        stream = _LogStream(self._log_newline, self._log_overwrite)
        threading.Thread(
            target=self._run_pipeline,
            args=(config, stream, self._cancel_event),
            daemon=True,
        ).start()

    def _on_cancel(self, _event) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
            self._btn_cancel.Disable()
            self.SetStatusText(S("status_cancelling"))

    def _on_metronome_settings(self, _event) -> None:
        dlg = MetronomeDialog(self, self._click_a, self._click_b, self._count_in,
                              self._click_volume_db)
        if dlg.ShowModal() == wx.ID_OK:
            self._click_a, self._click_b, self._count_in, self._click_volume_db = dlg.get_values()
        dlg.Destroy()

    def _on_watermark_settings(self, _event) -> None:
        dlg = WatermarkDialog(self, self._watermark)
        if dlg.ShowModal() == wx.ID_OK:
            self._watermark = dlg.get_values()
            name = Path(self._watermark.path).name if self._watermark.path else S("watermark_none")
            self._watermark_summary.SetLabel(name)
        dlg.Destroy()

    def _on_help(self, _event) -> None:
        dlg = HelpDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def _run_pipeline(self, config: PipelineConfig, stream,
                      cancel_event: threading.Event) -> None:
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = stream
        sys.stderr = stream
        try:
            generate_mp4(
                ly_path=config.ly, sf2_path=config.sf2, out_path=config.out_mp4,
                width=config.width, height=config.height, fps=config.fps,
                tempo_bpm=config.tempo_bpm,
                lilypond_exe=config.lilypond_exe,
                ffmpeg_exe=config.ffmpeg_exe,
                fluidsynth_exe=config.fluidsynth_exe,
                cursor_line=config.cursor_line, cursor_color=config.cursor_color,
                cursor_width=config.cursor_width,
                trail=config.trail,
                note_highlight=config.note_highlight, highlight_color=config.highlight_color,
                overlay_title=config.overlay_title, overlay_footer=config.overlay_footer,
                use_bar_timing=config.use_bar_timing, bar_numbers=config.bar_numbers,
                metronome=config.metronome,
                click_accent=config.click_a, click_beat=config.click_b,
                count_in_bars=config.count_in_bars,
                fade_frames=config.fade_frames,
                watermark=config.watermark,
                fill_height=config.fill_height,
                volume_db=config.volume_db, click_volume_db=config.click_volume_db,
                cancel_event=cancel_event,
            )
            wx.CallAfter(self._pipeline_done, success=True, cancelled=False,
                         path=config.out_mp4)
        except InterruptedError:
            wx.CallAfter(self._pipeline_done, success=False, cancelled=True,
                         path=config.out_mp4)
        except Exception as exc:
            wx.CallAfter(self._log_newline, S("log_error", exc=exc))
            wx.CallAfter(self._pipeline_done, success=False, cancelled=False,
                         path=config.out_mp4)
        finally:
            sys.stdout = old_out
            sys.stderr = old_err

    def _pipeline_done(self, success: bool, cancelled: bool, path: str) -> None:
        self._btn_mp4.Enable()
        self._btn_cancel.Disable()
        self._cancel_event = None
        if cancelled:
            self._log_newline(S("log_cancelled"))
            self.SetStatusText(S("status_cancelled"))
        elif success:
            self._log_newline(S("log_done", path=path))
            self.SetStatusText(S("status_done", filename=Path(path).name))
            self._btn_open_mp4.Enable()
            self._btn_open_folder.Enable()
            if self._auto_open_chk.GetValue():
                try:
                    os.startfile(path)
                except Exception:
                    pass
        else:
            self._log_newline(S("log_encoding_failed"))
            self.SetStatusText(S("status_encoding_failed"))

    # ------------------------------------------------------------------
    # Post-completion
    # ------------------------------------------------------------------

    def _on_open_mp4(self, _event) -> None:
        if self._mp4_path and Path(self._mp4_path).is_file():
            try:
                os.startfile(self._mp4_path)
            except Exception as exc:
                wx.MessageBox(str(exc), S("msg_cannot_open_mp4_title"), wx.ICON_ERROR)

    def _on_open_folder(self, _event) -> None:
        if self._mp4_path:
            subprocess.Popen(["explorer", str(Path(self._mp4_path).parent)])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    app = wx.App()
    MainFrame()
    app.MainLoop()


if __name__ == "__main__":
    main()
