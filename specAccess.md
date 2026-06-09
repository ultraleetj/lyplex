# LyPlex GUI Accessibility Spec

Decisions and patterns established in `lyplex_gui.py`. Apply to all future GUI work.

---

## Screen Reader Labels

Every interactive control must have an accessible name set via `name=` in the constructor **and** tracked for language switching. This applies to **all** interactive widget types: `wx.SpinCtrl`, `wx.Choice`, `wx.TextCtrl`, `wx.Button`.

```python
ctrl = wx.SpinCtrl(panel, ..., name=S("accessible_key"))
self._i18n.append((ctrl, "accessible_key", "SetName"))
```

Use `_tn(ctrl, key)` helper — sets `SetName` now and registers for i18n refresh.  
Use `_t(widget, key)` helper — registers `SetLabel` refresh (for StaticText, Button labels).

A control with a visible label (via `_t`) and an accessible name (via `_tn`) requires both calls. They can chain:

```python
btn = _tn(_t(wx.Button(panel, label=S("btn_browse")), "btn_browse"), label_key)
```

This sets the visible label to `S("btn_browse")` and the accessible name to `S(label_key)`, both tracked for language switch.

---

## Label-Before-Control DOM Order

StaticText labels **must** be added to the sizer before their associated control.  
UIA/NVDA traverse focus order matches widget creation order — label after control breaks association.

```python
lbl = wx.StaticText(panel, label=S(label_key))   # created first
ctrl = wx.SpinCtrl(panel, ...)                    # created second
grid.Add(lbl, ...)
grid.Add(ctrl, ...)
```

---

## SpinCtrl vs SpinCtrlDouble

Use `wx.SpinCtrl` (integer) for any screen-reader-accessible spin field.

**Never use `wx.SpinCtrlDouble` in the main window.**

`wx.SpinCtrlDouble` is a composite Windows control. NVDA/JAWS focus the inner edit HWND, which does not inherit the accessible name set on the outer container. `SetName()`, `SetHelpText()`, and the `name=` constructor param all fail to reach the inner control.

`wx.SpinCtrl` (native integer spin) works correctly with all screen readers.

**For float fields needing integer UX (e.g., dB volumes):** use `wx.SpinCtrl` with integer dB range; promote to float in Python.

**Exception — dialogs only:** `wx.SpinCtrlDouble` is acceptable in secondary dialogs (MetronomeDialog, WatermarkDialog) where float precision matters and screen reader coverage is lower priority. As of current code this exception is not exercised — those dialogs also use `wx.SpinCtrl`.

**For float fields needing decimal input (e.g., tempo BPM):** use `wx.TextCtrl` + `wx.SpinButton` pair (`spin_double_row` pattern). Clamp on `EVT_KILL_FOCUS`. SpinButton has no accessible name requirement (it's a visual nudge only; text field is the actual control). The `wx.TextCtrl` in this pair **must** have `_tn(tc, label_key)` applied.

---

## Accessible Names on Choice and TextCtrl

The `_tn()` / `SetName()` rule applies to every interactive widget, not only `wx.SpinCtrl`.

**`wx.Choice`** — set name to the field's label key:
```python
ch = _tn(wx.Choice(panel, choices=items), label_key)
```

**`wx.TextCtrl`** (file/dir pickers, float text fields) — set name to the field's label key:
```python
tc = _tn(wx.TextCtrl(panel, value=default), label_key)
```

UIA does not automatically associate a preceding `wx.StaticText` with the next `wx.TextCtrl` or `wx.Choice`. Proximity is not enough — `SetName()` is required.

---

## Browse Button Uniqueness

Every file/dir picker row produces a "Browse" button. All share the same visible label.  
Without a distinct accessible name, screen readers announce six identical "Browse" buttons with no context.

Set the Browse button's accessible name to the **field's label key** (not the generic browse key):
```python
btn = _tn(_t(wx.Button(panel, label=S("btn_browse")), "btn_browse"), label_key)
```

Result: screen reader announces "LilyPond file Browse button", "SoundFont Browse button", etc.  
The visible label stays "Browse" (or translated equivalent). Both update on language switch.

---

## Color Selection

Use `wx.Choice` with named color presets instead of `wx.ColourPickerCtrl`.

`wx.ColourPickerCtrl` opens a color dialog that is not keyboard-navigable. Named presets in a `wx.Choice` are fully keyboard and screen-reader accessible.

The `wx.Choice` must have `_tn(ch, label_key)` applied (see Accessible Names on Choice section above).

Add a `wx.Panel` swatch (20×20, `SetBackgroundColour`) next to the choice as a visual-only indicator — no accessible name needed on swatch.

Update swatch on `EVT_CHOICE`:
```python
ch.Bind(wx.EVT_CHOICE, _update_swatch)
```

---

## Status Bar

Use `wx.Frame.CreateStatusBar()` + `SetStatusText()` for all pipeline state changes.  
Keys used: `status_ready`, `status_encoding`, `status_cancelling`, `status_cancelled`, `status_done`, `status_encoding_failed`.

Screen readers announce status bar text. Do not duplicate these announcements in the log.

---

## Log TextCtrl

Must have an accessible name:
```python
self._log = wx.TextCtrl(panel, style=..., name=S("log_accessible_name"))
```

Style: `wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP | wx.HSCROLL`.  
Monospace font. Screen readers can navigate log lines.

---

## Button States

Buttons must reflect enabled/disabled state accurately at all times:

| Button | Enabled when |
|--------|-------------|
| Encode MP4 | Always (unless encoding in progress) |
| Cancel | Only while encoding |
| Open MP4 | After successful encode |
| Open Folder | After successful encode |

Use `Enable()` / `Disable()` — not hiding. Hidden controls confuse screen reader tab order.

---

## Dialog Buttons

Use `wx.Dialog.CreateButtonSizer(wx.OK | wx.CANCEL)` for all dialogs.  
Provides standard accessible OK/Cancel with correct keyboard handling (Enter = OK, Escape = Cancel).

Escape close in non-standard dialogs (e.g., HelpDialog with only a Close button):
```python
self.Bind(wx.EVT_CHAR_HOOK, lambda e: self.EndModal(wx.ID_CLOSE)
          if e.GetKeyCode() == wx.WXK_ESCAPE else e.Skip())
```

---

## Language Switching

All accessible names must update when language changes.

`_apply_language()` iterates `self._i18n` and calls either `SetLabel` or `SetName` based on the tracked method. Color choice items are re-populated with translated names while preserving selection index.

Pattern: every control registered with `_t()` or `_tn()` at construction time is automatically updated.

Do not hardcode English strings in `name=` or `label=` — always use `S("key")`.

---

## Grid Layout (FlexGridSizer)

3-column grid: label | control | hint/unit.  
`AddGrowableCol(1, 1)` — control column stretches.  
Empty cells: `grid.AddSpacer(0)` to maintain column count — never skip cells.

---

## Summary of Forbidden Patterns

| Pattern | Reason | Use instead |
|---------|--------|-------------|
| `wx.SpinCtrlDouble` in main window | Inner HWND hides accessible name | `wx.SpinCtrl` (int) |
| `wx.ColourPickerCtrl` | Not keyboard-navigable | `wx.Choice` + swatch panel |
| `wx.Choice` without `_tn()` | Screen reader sees unnamed dropdown | `_tn(ch, label_key)` |
| `wx.TextCtrl` without `_tn()` | UIA proximity ≠ association | `_tn(tc, label_key)` |
| Browse buttons with generic label only | Six identical "Browse" — no context | `_tn(btn, label_key)` for name |
| Hardcoded strings in `name=` | Breaks language switch | `S("key")` + `_tn()` |
| Label added after control | Wrong UIA traversal order | Label first, control second |
| `Hide()` instead of `Disable()` | Breaks tab order | `Enable(False)` |
| `wx.MessageBox` for status updates | Not screen-reader-friendly | `SetStatusText()` on status bar |
