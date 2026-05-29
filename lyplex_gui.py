"""
lyplex_gui.py — accessible wxPython GUI for LyPlex pipeline
Run: python lyplex_gui.py
"""

from __future__ import annotations

import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

import wx

from lyplex_tool import DEFAULT_FPS, DEFAULT_HEIGHT, DEFAULT_WIDTH, generate_mp4

HERE = Path(__file__).parent

def _default(rel: str) -> str:
    """Return absolute path for a bundled file if it exists, else empty string."""
    p = HERE / rel
    return str(p) if p.exists() else ""


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
        super().__init__(None, title="LyPlex — Scrolling Sheet Music", size=(740, 860))
        self._mp4_path: str | None = None
        self._html_path: str | None = None
        self._overwriting_log_line = False
        self._build_ui()
        self.CreateStatusBar()
        self.SetStatusText("Ready.")
        self.Centre()
        self.Show()

    # ------------------------------------------------------------------
    # UI — labels always created before their controls (UIA LabeledBy z-order)
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)

        grid = wx.FlexGridSizer(cols=3, hgap=6, vgap=8)
        grid.AddGrowableCol(1, 1)

        # LilyPond file — label before picker
        ly_lbl = wx.StaticText(panel, label="LilyPond score (.ly):")
        self._ly_picker = wx.FilePickerCtrl(
            panel,
            wildcard="LilyPond files (*.ly)|*.ly|All files (*.*)|*.*",
            style=wx.FLP_DEFAULT_STYLE | wx.FLP_USE_TEXTCTRL,
            name="LilyPond source file, dot ly extension",
        )
        grid.Add(ly_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._ly_picker, 1, wx.EXPAND)
        grid.Add(wx.StaticText(panel, label="(sheet music source)"), 0, wx.ALIGN_CENTER_VERTICAL)

        # Soundfont — label before picker
        sf_lbl = wx.StaticText(panel, label="Soundfont (.sf2):")
        self._sf2_picker = wx.FilePickerCtrl(
            panel,
            path=_default("soundfonts/GeneralUser-GS.sf2"),
            wildcard="Soundfont files (*.sf2)|*.sf2|All files (*.*)|*.*",
            style=wx.FLP_DEFAULT_STYLE | wx.FLP_USE_TEXTCTRL,
            name="SoundFont file, dot sf2 extension",
        )
        grid.Add(sf_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._sf2_picker, 1, wx.EXPAND)
        grid.Add(wx.StaticText(panel, label="(instrument samples for audio)"), 0, wx.ALIGN_CENTER_VERTICAL)

        # LilyPond binary — label before picker
        ly_bin_lbl = wx.StaticText(panel, label="LilyPond binary:")
        self._lilypond_picker = wx.FilePickerCtrl(
            panel,
            path=_default(""),  # not bundled — user must have it installed
            wildcard="Executables (*.exe)|*.exe|All files (*.*)|*.*",
            style=wx.FLP_DEFAULT_STYLE | wx.FLP_USE_TEXTCTRL,
            name="LilyPond executable path, leave blank to use PATH",
        )
        grid.Add(ly_bin_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._lilypond_picker, 1, wx.EXPAND)
        grid.Add(wx.StaticText(panel, label="(blank = use system PATH)"), 0, wx.ALIGN_CENTER_VERTICAL)

        # ffmpeg binary — label before picker
        ffmpeg_lbl = wx.StaticText(panel, label="ffmpeg binary:")
        self._ffmpeg_picker = wx.FilePickerCtrl(
            panel,
            path=_default("bin/ffmpeg.exe"),
            wildcard="Executables (*.exe)|*.exe|All files (*.*)|*.*",
            style=wx.FLP_DEFAULT_STYLE | wx.FLP_USE_TEXTCTRL,
            name="ffmpeg executable path",
        )
        grid.Add(ffmpeg_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._ffmpeg_picker, 1, wx.EXPAND)
        grid.Add(wx.StaticText(panel, label="(blank = use system PATH)"), 0, wx.ALIGN_CENTER_VERTICAL)

        # fluidsynth binary — label before picker
        fs_lbl = wx.StaticText(panel, label="fluidsynth binary:")
        self._fluidsynth_picker = wx.FilePickerCtrl(
            panel,
            path=_default("bin/fluidsynth/fluidsynth.exe"),
            wildcard="Executables (*.exe)|*.exe|All files (*.*)|*.*",
            style=wx.FLP_DEFAULT_STYLE | wx.FLP_USE_TEXTCTRL,
            name="fluidsynth executable path",
        )
        grid.Add(fs_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._fluidsynth_picker, 1, wx.EXPAND)
        grid.Add(wx.StaticText(panel, label="(blank = use system PATH)"), 0, wx.ALIGN_CENTER_VERTICAL)

        # Output folder — label before picker
        dir_lbl = wx.StaticText(panel, label="Output folder:")
        self._dir_picker = wx.DirPickerCtrl(
            panel,
            style=wx.DIRP_DEFAULT_STYLE | wx.DIRP_USE_TEXTCTRL,
            name="Output folder for the encoded MP4",
        )
        grid.Add(dir_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._dir_picker, 1, wx.EXPAND)
        grid.Add(wx.StaticText(panel, label="(where to save the MP4)"), 0, wx.ALIGN_CENTER_VERTICAL)

        # Resolution — label before spinners
        res_lbl = wx.StaticText(panel, label="Resolution (W × H):")
        self._width_ctrl = wx.SpinCtrl(
            panel, min=320, max=7680, initial=DEFAULT_WIDTH, size=(90, -1),
            name="Output width in pixels, must be an even number",
        )
        self._height_ctrl = wx.SpinCtrl(
            panel, min=240, max=4320, initial=DEFAULT_HEIGHT, size=(90, -1),
            name="Output height in pixels, must be an even number",
        )
        res_box = wx.BoxSizer(wx.HORIZONTAL)
        res_box.Add(self._width_ctrl)
        # StaticText separator is presentational — no name needed
        res_box.Add(wx.StaticText(panel, label=" × "), 0, wx.ALIGN_CENTER_VERTICAL)
        res_box.Add(self._height_ctrl)
        grid.Add(res_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(res_box)
        grid.AddSpacer(0)

        # FPS — label before spinner
        fps_lbl = wx.StaticText(panel, label="Frame rate (fps):")
        self._fps_ctrl = wx.SpinCtrl(
            panel, min=15, max=60, initial=DEFAULT_FPS, size=(90, -1),
            name="Frame rate in frames per second",
        )
        grid.Add(fps_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._fps_ctrl)
        grid.AddSpacer(0)

        # Tempo multiplier — label before spinner
        tempo_lbl = wx.StaticText(panel, label="Tempo multiplier:")
        self._tempo_ctrl = wx.SpinCtrlDouble(
            panel, min=0.25, max=4.0, initial=1.0, inc=0.05, size=(90, -1),
            name="Tempo multiplier: 1.0 is original speed, 0.5 is half speed, 2.0 is double speed. "
                 "Scales both scroll timing and audio playback rate.",
        )
        self._tempo_ctrl.SetDigits(2)
        tempo_hint = wx.StaticText(panel, label="(1.0 = original speed)")
        grid.Add(tempo_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._tempo_ctrl)
        grid.Add(tempo_hint, 0, wx.ALIGN_CENTER_VERTICAL)

        # Cursor line option
        cursor_lbl = wx.StaticText(panel, label="Playback cursor:")
        self._cursor_chk = wx.CheckBox(
            panel, label="Show vertical cursor line",
            name="Show a vertical cursor line on the video at the current playback position",
        )
        grid.Add(cursor_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._cursor_chk)
        grid.AddSpacer(0)

        # Trail option
        trail_lbl = wx.StaticText(panel, label="Note trail:")
        self._trail_chk = wx.CheckBox(
            panel, label="Show fading dot trail + played-region tint",
            name="Overlay fading dots at past notehead positions and a color tint over the played region",
        )
        grid.Add(trail_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._trail_chk)
        grid.AddSpacer(0)

        # Title overlay
        title_ov_lbl = wx.StaticText(panel, label="Title overlay:")
        self._title_overlay_chk = wx.CheckBox(
            panel, label="Show title / composer (fixed, does not scroll)",
            name="Show title, subtitle, and composer as a fixed overlay band at the top of the video",
        )
        grid.Add(title_ov_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._title_overlay_chk)
        grid.Add(wx.StaticText(panel, label="(from \\header in .ly)"), 0, wx.ALIGN_CENTER_VERTICAL)

        # Footer overlay
        footer_ov_lbl = wx.StaticText(panel, label="Footer overlay:")
        self._footer_overlay_chk = wx.CheckBox(
            panel, label="Show copyright / tagline (fixed, does not scroll)",
            name="Show copyright or tagline as a fixed overlay band at the bottom of the video",
        )
        grid.Add(footer_ov_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._footer_overlay_chk)
        grid.Add(wx.StaticText(panel, label="(from \\header in .ly)"), 0, wx.ALIGN_CENTER_VERTICAL)

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

        # Log — label before text ctrl
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
        ly = self._ly_picker.GetPath()
        sf2 = self._sf2_picker.GetPath()
        out_dir = self._dir_picker.GetPath()

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

        out_mp4 = str(Path(out_dir) / f"{Path(ly).stem}.mp4")
        self._mp4_path = out_mp4

        fps = self._fps_ctrl.GetValue()
        tempo = self._tempo_ctrl.GetValue()
        cursor_line = self._cursor_chk.GetValue()
        trail = self._trail_chk.GetValue()
        overlay_title = self._title_overlay_chk.GetValue()
        overlay_footer = self._footer_overlay_chk.GetValue()
        lilypond_exe = self._lilypond_picker.GetPath() or None
        ffmpeg_exe = self._ffmpeg_picker.GetPath() or None
        fluidsynth_exe = self._fluidsynth_picker.GetPath() or None

        self._log.Clear()
        self._overwriting_log_line = False
        self._btn_mp4.Disable()
        self._btn_explorer.Disable()
        self.SetStatusText("Encoding…")

        stream = _LogStream(self._log_newline, self._log_overwrite)
        threading.Thread(
            target=self._run_pipeline,
            args=(ly, sf2, out_mp4, width, height, fps, tempo, cursor_line, trail,
                  overlay_title, overlay_footer, lilypond_exe, ffmpeg_exe, fluidsynth_exe, stream),
            daemon=True,
        ).start()

    def _run_pipeline(
        self, ly, sf2, out_mp4, width, height, fps, tempo, cursor_line, trail,
        overlay_title, overlay_footer, lilypond_exe, ffmpeg_exe, fluidsynth_exe, stream
    ) -> None:
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = stream
        sys.stderr = stream
        try:
            generate_mp4(
                ly_path=ly,
                sf2_path=sf2,
                out_path=out_mp4,
                width=width,
                height=height,
                fps=fps,
                tempo_multiplier=tempo,
                lilypond_exe=lilypond_exe,
                ffmpeg_exe=ffmpeg_exe,
                fluidsynth_exe=fluidsynth_exe,
                cursor_line=cursor_line,
                trail=trail,
                overlay_title=overlay_title,
                overlay_footer=overlay_footer,
            )
            wx.CallAfter(self._pipeline_done, success=True, path=out_mp4)
        except Exception as exc:
            wx.CallAfter(self._log_newline, f"\nERROR: {exc}")
            wx.CallAfter(self._pipeline_done, success=False, path=out_mp4)
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
