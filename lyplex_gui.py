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
        super().__init__(None, title="LyPlex — Scrolling Sheet Music", size=(740, 900))
        self._mp4_path: str | None = None
        self._html_path: str | None = None
        self._overwriting_log_line = False
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
            str(HERE),
            hint="(where to save the MP4)")

        # --- numeric rows ---

        grid.Add(wx.StaticText(panel, label="Resolution (W × H):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._width_ctrl = wx.SpinCtrl(panel, min=320, max=7680, initial=DEFAULT_WIDTH, size=(90, -1))
        self._height_ctrl = wx.SpinCtrl(panel, min=240, max=4320, initial=DEFAULT_HEIGHT, size=(90, -1))
        res_box = wx.BoxSizer(wx.HORIZONTAL)
        res_box.Add(self._width_ctrl)
        res_box.Add(wx.StaticText(panel, label=" × "), 0, wx.ALIGN_CENTER_VERTICAL)
        res_box.Add(self._height_ctrl)
        grid.Add(res_box)
        grid.AddSpacer(0)

        grid.Add(wx.StaticText(panel, label="Frame rate (fps):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._fps_ctrl = wx.SpinCtrl(panel, min=15, max=60, initial=DEFAULT_FPS, size=(90, -1))
        grid.Add(self._fps_ctrl)
        grid.AddSpacer(0)

        self._tempo_tc = spin_double_row(
            "Tempo multiplier:", 0.25, 4.0, 1.0, 0.05, 2,
            hint="(1.0 = original speed)")

        # --- overlay / option checkboxes ---

        self._cursor_chk = chk_row(
            "Playback cursor:", "Show vertical cursor line")
        self._trail_chk = chk_row(
            "Note trail:", "Show fading dot trail + played-region tint")
        self._title_overlay_chk = chk_row(
            "Title overlay:", "Show title / composer (fixed, does not scroll)",
            hint=r"(from \header in .ly)")
        self._footer_overlay_chk = chk_row(
            "Footer overlay:", "Show copyright / tagline (fixed, does not scroll)",
            hint=r"(from \header in .ly)")

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
        trail = self._trail_chk.GetValue()
        overlay_title = self._title_overlay_chk.GetValue()
        overlay_footer = self._footer_overlay_chk.GetValue()
        lilypond_exe = self._lilypond_tc.GetValue().strip() or None
        ffmpeg_exe = self._ffmpeg_tc.GetValue().strip() or None
        fluidsynth_exe = self._fluidsynth_tc.GetValue().strip() or None

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
