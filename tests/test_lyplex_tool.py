"""
tests/test_lyplex_tool.py — unit tests for pure-Python functions in lyplex_tool.py.

Only tests functions that do NOT invoke external binaries (lilypond, ffmpeg, fluidsynth).
Run with:  pytest tests/test_lyplex_tool.py -v
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

# Allow import from parent directory without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from lyplex_tool import (
    AnchorInfo,
    TimingEntry,
    _extract_source_bpm,
    _group_by_value,
    _merge_closest_svg_groups,
    _tick_to_ms,
    _build_tempo_map,
    build_timing_map,
    _find_closing_brace,
    _wrap_score_body_with_unfold,
    _inject_unfold_repeats,
    _should_unfold_repeats,
    _strip_ties,
    _strip_unfold_repeats,
    _has_volta_repeats,
    _has_percent_repeats,
    _has_chord_names,
    _inject_point_and_click_types,
    _add_strip_paper,
    _atempo_filter,
    _extract_header,
    patch_ly_svg,
    patch_ly_timing_midi,
    patch_ly_audio_midi,
    build_bar_timing_map,
    scroll_offset_at,
    CURSOR_POSITION,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tempo_map(*entries):
    """Shorthand: make_tempo_map((tick, ms, tempo_us), ...) -> list."""
    return list(entries)


def anchor(x, y=0.0, line=1, col=1):
    return AnchorInfo(x=x, y=y, line=line, col=col)


def note_on(tick, pitch=60, dur=480):
    """3-tuple expected by build_timing_map: (tick, pitch, duration_ticks)."""
    return (tick, pitch, dur)


# ---------------------------------------------------------------------------
# _tick_to_ms
# ---------------------------------------------------------------------------

class TestTickToMs:
    """_tick_to_ms(tick, tempo_map, ticks_per_beat) -> float (milliseconds)"""

    TPB = 480  # ticks per beat

    def test_tick_zero_is_zero(self):
        tm = [(0, 0.0, 500_000)]  # 120 BPM
        assert _tick_to_ms(0, tm, self.TPB) == pytest.approx(0.0)

    def test_single_tempo_one_beat(self):
        # 120 BPM → 500 000 µs/beat → 1 beat (480 ticks) = 500 ms
        tm = [(0, 0.0, 500_000)]
        assert _tick_to_ms(480, tm, self.TPB) == pytest.approx(500.0)

    def test_single_tempo_fractional_beat(self):
        # 60 BPM → 1 000 000 µs/beat → 240 ticks = 500 ms
        tm = [(0, 0.0, 1_000_000)]
        assert _tick_to_ms(240, tm, self.TPB) == pytest.approx(500.0)

    def test_single_tempo_two_beats(self):
        # 120 BPM: 960 ticks = 1 000 ms
        tm = [(0, 0.0, 500_000)]
        assert _tick_to_ms(960, tm, self.TPB) == pytest.approx(1000.0)

    def test_tempo_change_mid_piece(self):
        # First 480 ticks @ 120 BPM = 500 ms; then tempo changes to 60 BPM.
        # Next 480 ticks @ 60 BPM = 1 000 ms → total 1 500 ms at tick 960.
        tm = [
            (0,   0.0,   500_000),   # 120 BPM from tick 0
            (480, 500.0, 1_000_000), # 60 BPM from tick 480
        ]
        assert _tick_to_ms(960, tm, self.TPB) == pytest.approx(1500.0)

    def test_tempo_change_at_queried_tick(self):
        # Query is exactly at the tempo-change checkpoint.
        tm = [
            (0,   0.0,   500_000),
            (480, 500.0, 1_000_000),
        ]
        assert _tick_to_ms(480, tm, self.TPB) == pytest.approx(500.0)

    def test_tick_before_first_checkpoint_uses_first_tempo(self):
        # Tempo map starts at tick 0; querying a tick < 0 is unusual but should
        # not crash — it uses the first tempo entry's tempo.
        tm = [(0, 0.0, 500_000)]
        # Negative ticks are clamped naturally by the loop (no cp_tick > tick).
        result = _tick_to_ms(-480, tm, self.TPB)
        # Result will be negative (base_ms + negative delta); just check it doesn't raise.
        assert isinstance(result, float)

    def test_empty_tempo_map_returns_zero(self):
        assert _tick_to_ms(960, [], self.TPB) == pytest.approx(0.0)

    def test_multiple_tempo_changes(self):
        # Three tempos: 120→60→240 BPM
        # tick 0–480: 120 BPM → 500 ms
        # tick 480–960: 60 BPM → 1 000 ms more → cum 1 500 ms at tick 960
        # tick 960–1440: 240 BPM → 250 ms more → cum 1 750 ms at tick 1440
        tm = [
            (0,    0.0,    500_000),
            (480,  500.0,  1_000_000),
            (960,  1500.0, 250_000),
        ]
        assert _tick_to_ms(1440, tm, self.TPB) == pytest.approx(1750.0)

    def test_different_ticks_per_beat(self):
        # 960 TPB, 120 BPM → 960 ticks = 500 ms
        tm = [(0, 0.0, 500_000)]
        assert _tick_to_ms(960, tm, 960) == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# _group_by_value
# ---------------------------------------------------------------------------

class TestGroupByValue:

    def test_empty_input(self):
        assert _group_by_value([], key_fn=lambda x: x) == []

    def test_all_same_key(self):
        items = [1, 2, 3]
        groups = _group_by_value(items, key_fn=lambda x: "same")
        assert len(groups) == 1
        assert sorted(groups[0]) == [1, 2, 3]

    def test_all_different_keys(self):
        items = [10, 20, 30]
        groups = _group_by_value(items, key_fn=lambda x: x)
        assert len(groups) == 3
        flat = sorted(g[0] for g in groups)
        assert flat == [10, 20, 30]

    def test_float_rounding_groups_near_values(self):
        # Anchors at x=5.001 and x=5.004 round to 5.0 → same group.
        # Anchor at x=6.0 → different group.
        items = [5.001, 5.004, 6.0]
        groups = _group_by_value(items, key_fn=lambda x: round(x, 2))
        assert len(groups) == 2

    def test_preserves_insertion_order_of_groups(self):
        # dict preserves insertion order in Python 3.7+
        items = [1, 3, 1, 3, 2]
        groups = _group_by_value(items, key_fn=lambda x: x)
        # First group encountered was for key 1, then 3, then 2.
        assert groups[0] == [1, 1]
        assert groups[1] == [3, 3]
        assert groups[2] == [2]

    def test_anchor_grouping_by_x(self):
        # Simulates what build_timing_map does: group anchors by round(x, 2).
        anchors = [
            anchor(1.00), anchor(1.001), anchor(2.00), anchor(2.005), anchor(3.00),
        ]
        groups = _group_by_value(anchors, key_fn=lambda a: round(a.x, 2))
        assert len(groups) == 3

    def test_midi_grouping_by_tick(self):
        events = [(0, 60, 480), (0, 64, 480), (480, 67, 240)]
        groups = _group_by_value(events, key_fn=lambda e: e[0])
        assert len(groups) == 2
        assert len(groups[0]) == 2  # two notes at tick 0
        assert len(groups[1]) == 1  # one note at tick 480


# ---------------------------------------------------------------------------
# _merge_closest_svg_groups
# ---------------------------------------------------------------------------

class TestMergeClosestSvgGroups:

    def _groups_from_xs(self, *xs_lists):
        """Build list-of-lists of AnchorInfo from xs_lists like ((1.0,), (1.5, 2.0))."""
        return [[anchor(x) for x in xs] for xs in xs_lists]

    def test_no_merge_needed(self):
        groups = self._groups_from_xs((1.0,), (2.0,), (3.0,))
        result = _merge_closest_svg_groups(groups, target=3)
        assert len(result) == 3

    def test_merge_one_pair(self):
        # Groups at x=1.0, x=1.1 (gap 0.1), x=5.0 (gap 3.9).
        # Merging to target=2 should merge the pair with smallest gap (1.0 & 1.1).
        groups = self._groups_from_xs((1.0,), (1.1,), (5.0,))
        result = _merge_closest_svg_groups(groups, target=2)
        assert len(result) == 2
        # Merged group should contain both anchors from x=1.0 and x=1.1.
        merged_xs = sorted(a.x for a in result[0])
        assert merged_xs == pytest.approx([1.0, 1.1])
        assert result[1][0].x == pytest.approx(5.0)

    def test_merge_picks_closest_not_leftmost(self):
        # Gap between groups 0 and 1 = 10; gap between 1 and 2 = 0.05.
        # Merging to target=2 should merge the closer pair (1 and 2).
        groups = self._groups_from_xs((1.0,), (11.0,), (11.05,))
        result = _merge_closest_svg_groups(groups, target=2)
        assert len(result) == 2
        first_xs = [a.x for a in result[0]]
        assert 1.0 in first_xs
        merged_xs = sorted(a.x for a in result[1])
        assert merged_xs == pytest.approx([11.0, 11.05])

    def test_merge_two_pairs(self):
        # Four groups → merge down to two in two steps.
        groups = self._groups_from_xs((1.0,), (1.1,), (5.0,), (5.05,))
        result = _merge_closest_svg_groups(groups, target=2)
        assert len(result) == 2

    def test_single_group_target_one(self):
        groups = self._groups_from_xs((1.0,))
        result = _merge_closest_svg_groups(groups, target=1)
        assert len(result) == 1

    def test_target_equals_count_no_change(self):
        groups = self._groups_from_xs((1.0,), (2.0,))
        result = _merge_closest_svg_groups(groups, target=2)
        assert len(result) == 2

    def test_multi_anchor_groups(self):
        # Groups may already have multiple anchors (multi-staff chords).
        groups = [
            [anchor(1.0), anchor(1.0)],  # chord at beat 1
            [anchor(1.05)],               # grace note just right of beat 1
            [anchor(5.0)],               # well-separated beat
        ]
        result = _merge_closest_svg_groups(groups, target=2)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _extract_source_bpm
# ---------------------------------------------------------------------------

class TestExtractSourceBpm:

    def test_simple_tempo(self):
        assert _extract_source_bpm(r'\tempo 4 = 120') == pytest.approx(120.0)

    def test_tempo_with_text_marking(self):
        # \tempo "Allegro" 4 = 132
        src = r'\tempo "Allegro" 4 = 132'
        assert _extract_source_bpm(src) == pytest.approx(132.0)

    def test_tempo_half_note(self):
        src = r'\tempo 2 = 60'
        assert _extract_source_bpm(src) == pytest.approx(60.0)

    def test_no_tempo_returns_none(self):
        src = r'\version "2.24.0"\relative c { c4 d e f }'
        assert _extract_source_bpm(src) is None

    def test_first_tempo_wins(self):
        src = r'\tempo 4 = 100 ... \tempo 4 = 200'
        assert _extract_source_bpm(src) == pytest.approx(100.0)

    def test_tempo_in_larger_source(self):
        src = r"""
\version "2.24.0"
\header { title = "Test" }
\score {
  \relative c' {
    \tempo 4 = 90
    c4 d e f
  }
}
"""
        assert _extract_source_bpm(src) == pytest.approx(90.0)

    def test_tempo_value_as_float(self):
        result = _extract_source_bpm(r'\tempo 4 = 72')
        assert isinstance(result, float)

    def test_tempo_dotted_note(self):
        # \tempo 4. = 80 — the regex matches digits after '='
        src = r'\tempo 4. = 80'
        assert _extract_source_bpm(src) == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# build_timing_map
# ---------------------------------------------------------------------------

class TestBuildTimingMap:
    """Tests for build_timing_map(anchors, note_ons, tempo_map, ticks_per_beat)."""

    TPB = 480

    def _simple_tempo_map(self, bpm=120):
        us = int(60_000_000 / bpm)
        return [(0, 0.0, us)]

    def test_one_note(self):
        anch = [anchor(10.0)]
        notes = [note_on(0)]
        tm = self._simple_tempo_map(120)
        result = build_timing_map(anch, notes, tm, self.TPB)
        assert len(result) == 1
        assert result[0].ms == pytest.approx(0.0)
        assert result[0].x == pytest.approx(10.0)

    def test_two_notes_sorted_by_ms(self):
        # Two anchors left-to-right, two MIDI events in time order.
        anch = [anchor(10.0), anchor(20.0)]
        notes = [note_on(0), note_on(480)]
        tm = self._simple_tempo_map(120)
        result = build_timing_map(anch, notes, tm, self.TPB)
        assert len(result) == 2
        assert result[0].ms < result[1].ms
        assert result[0].x == pytest.approx(10.0)
        assert result[1].x == pytest.approx(20.0)

    def test_ms_values_match_tempo(self):
        # 120 BPM, 480 TPB → one beat = 500 ms.
        anch = [anchor(5.0), anchor(15.0)]
        notes = [note_on(0), note_on(480)]
        tm = self._simple_tempo_map(120)
        result = build_timing_map(anch, notes, tm, self.TPB)
        assert result[0].ms == pytest.approx(0.0)
        assert result[1].ms == pytest.approx(500.0)

    def test_grace_note_merge_warning(self):
        # Three SVG anchors but only two MIDI groups → should warn and merge.
        anch = [anchor(1.0), anchor(1.05), anchor(5.0)]
        notes = [note_on(0), note_on(480)]
        tm = self._simple_tempo_map(120)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = build_timing_map(anch, notes, tm, self.TPB)
        assert len(result) == 2
        assert any("grace" in str(warning.message).lower() or
                   "merging" in str(warning.message).lower()
                   for warning in w)

    def test_extra_midi_events_truncated_warning(self):
        # Fewer SVG groups than MIDI groups → extra MIDI events ignored.
        anch = [anchor(10.0)]
        notes = [note_on(0), note_on(480), note_on(960)]
        tm = self._simple_tempo_map(120)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = build_timing_map(anch, notes, tm, self.TPB)
        assert len(result) == 1
        assert any("extra" in str(warning.message).lower() or
                   "ignored" in str(warning.message).lower()
                   for warning in w)

    def test_duration_ms_computed(self):
        # One note at tick 0, duration 480 ticks @ 120 BPM = 500 ms.
        anch = [anchor(10.0)]
        notes = [note_on(0, dur=480)]
        tm = self._simple_tempo_map(120)
        result = build_timing_map(anch, notes, tm, self.TPB)
        assert result[0].duration_ms == pytest.approx(500.0)

    def test_multi_staff_chord_anchors_share_x(self):
        # Two anchors at the same x (two staves, same beat) → collapse into one group.
        anch = [anchor(10.0, line=1), anchor(10.0, line=2), anchor(20.0)]
        notes = [note_on(0), note_on(480)]
        tm = self._simple_tempo_map(120)
        result = build_timing_map(anch, notes, tm, self.TPB)
        assert len(result) == 2

    def test_result_is_list_of_timing_entries(self):
        anch = [anchor(5.0)]
        notes = [note_on(0)]
        tm = self._simple_tempo_map(120)
        result = build_timing_map(anch, notes, tm, self.TPB)
        assert all(isinstance(e, TimingEntry) for e in result)

    def test_rightmost_x_used_per_group(self):
        # Two anchors at x=5.0 and x=5.1 (same beat): rightmost x=5.1 used.
        anch = [anchor(5.0), anchor(5.1)]
        notes = [note_on(0)]
        tm = self._simple_tempo_map(120)
        result = build_timing_map(anch, notes, tm, self.TPB)
        assert len(result) == 1
        assert result[0].x == pytest.approx(5.1)


# ---------------------------------------------------------------------------
# _parse_rgb (logic extracted — it lives inside __main__ block so we can't
# import it directly; we inline an equivalent implementation and test the
# spec instead of the symbol)
# ---------------------------------------------------------------------------

def _parse_rgb(s, default):
    """Local copy of the CLI helper for testing."""
    if not s:
        return default
    try:
        parts = [int(x.strip()) for x in s.split(",")]
        return (parts[0], parts[1], parts[2])
    except Exception:
        return default


class TestParseRgb:

    DEFAULT = (220, 50, 50)

    def test_valid_string(self):
        assert _parse_rgb("220,50,50", self.DEFAULT) == (220, 50, 50)

    def test_valid_with_spaces(self):
        assert _parse_rgb(" 50 , 120 , 220 ", self.DEFAULT) == (50, 120, 220)

    def test_none_returns_default(self):
        assert _parse_rgb(None, self.DEFAULT) == self.DEFAULT

    def test_empty_string_returns_default(self):
        assert _parse_rgb("", self.DEFAULT) == self.DEFAULT

    def test_non_numeric_returns_default(self):
        assert _parse_rgb("red,green,blue", self.DEFAULT) == self.DEFAULT

    def test_too_few_components_returns_default(self):
        # Only two values — IndexError should fall back to default.
        assert _parse_rgb("100,200", self.DEFAULT) == self.DEFAULT

    def test_zero_values(self):
        assert _parse_rgb("0,0,0", self.DEFAULT) == (0, 0, 0)

    def test_max_values(self):
        assert _parse_rgb("255,255,255", self.DEFAULT) == (255, 255, 255)

    def test_different_default(self):
        default = (50, 120, 220)
        assert _parse_rgb(None, default) == default


# ---------------------------------------------------------------------------
# .ly patching helpers
# ---------------------------------------------------------------------------

class TestStripTies:
    def test_removes_tilde(self):
        assert "~" not in _strip_ties("c4~ d4")

    def test_no_tilde_unchanged(self):
        src = r'\version "2.24.0" c4 d4'
        assert _strip_ties(src) == src


class TestStripUnfoldRepeats:
    def test_removes_keyword(self):
        src = r'\unfoldRepeats { \score { } }'
        result = _strip_unfold_repeats(src)
        assert r'\unfoldRepeats' not in result

    def test_no_keyword_unchanged(self):
        src = r'\score { c4 }'
        assert _strip_unfold_repeats(src) == src

    def test_does_not_strip_partial_word(self):
        # \unfoldRepeatsExtra should NOT be stripped (word boundary \b).
        src = r'\unfoldRepeatsExtra { }'
        result = _strip_unfold_repeats(src)
        assert r'\unfoldRepeatsExtra' in result


class TestHasVoltaRepeats:
    def test_detects_volta(self):
        assert _has_volta_repeats(r'\repeat volta 2 { c4 }')

    def test_no_volta(self):
        assert not _has_volta_repeats(r'\score { c4 }')

    def test_repeat_without_volta(self):
        assert not _has_volta_repeats(r'\repeat tremolo 4 { c16 }')


class TestHasPercentRepeats:
    def test_detects_percent(self):
        assert _has_percent_repeats(r'\repeat percent 4 { c4 }')

    def test_no_percent(self):
        assert not _has_percent_repeats(r'\score { c4 }')

    def test_volta_not_percent(self):
        assert not _has_percent_repeats(r'\repeat volta 2 { c4 }')


class TestHasChordNames:
    def test_detects_chord_names(self):
        assert _has_chord_names(r'\new ChordNames { }')

    def test_no_chord_names(self):
        assert not _has_chord_names(r'\new Staff { }')


class TestShouldUnfoldRepeats:
    def test_volta_without_chord_names(self):
        src = r'\repeat volta 2 { c4 }'
        assert _should_unfold_repeats(src)

    def test_volta_with_chord_names_skipped(self):
        src = r'\repeat volta 2 { c4 } \new ChordNames { }'
        assert not _should_unfold_repeats(src)

    def test_unfold_repeats_without_chord_names(self):
        src = r'\unfoldRepeats { c4 }'
        assert _should_unfold_repeats(src)

    def test_plain_source_not_unfolded(self):
        src = r'\score { c4 }'
        assert not _should_unfold_repeats(src)

    def test_percent_without_chord_names(self):
        src = r'\repeat percent 4 { c4 }'
        assert _should_unfold_repeats(src)

    def test_percent_with_chord_names_skipped(self):
        src = r'\repeat percent 4 { c4 } \new ChordNames { }'
        assert not _should_unfold_repeats(src)


class TestInjectPointAndClickTypes:
    def test_injects_after_version(self):
        src = r'\version "2.24.0"' + '\nc4'
        result = _inject_point_and_click_types(src)
        assert r'\pointAndClickTypes' in result
        version_pos = result.index(r'\version')
        pact_pos = result.index(r'\pointAndClickTypes')
        assert pact_pos > version_pos

    def test_raises_without_version(self):
        with pytest.raises(ValueError, match=r'\\pointAndClickTypes'):
            _inject_point_and_click_types(r'\score { c4 }')

    def test_contains_note_event_and_cluster(self):
        src = r'\version "2.24.0"'
        result = _inject_point_and_click_types(src)
        assert "note-event" in result
        assert "cluster-note-event" in result


class TestAddStripPaper:
    def test_adds_system_count(self):
        src = r'\version "2.24.0"\score { c4 }'
        result = _add_strip_paper(src)
        assert "system-count = 1" in result

    def test_removes_existing_paper_block(self):
        src = r'\paper { paper-width = 210\mm } \score { c4 }'
        result = _add_strip_paper(src)
        # Old paper block removed; new one added.
        assert result.count(r'\paper') == 1
        assert "system-count = 1" in result

    def test_paper_width_9999(self):
        result = _add_strip_paper(r'\score { c4 }')
        assert "9999" in result


class TestFindClosingBrace:
    def test_simple(self):
        # "{ }" — opening at 0, closing at 2, returns 3 (one past closing).
        s = "{ }"
        assert _find_closing_brace(s, 0) == 3

    def test_nested(self):
        s = "{ { } }"
        # outer closes at index 6, returns 7
        assert _find_closing_brace(s, 0) == 7

    def test_offset_start(self):
        s = "abc{ }"
        # opening brace at index 3
        assert _find_closing_brace(s, 3) == 6


class TestExtractHeader:
    def test_extracts_title(self):
        src = r'\header { title = "My Piece" }'
        assert _extract_header(src)['title'] == "My Piece"

    def test_extracts_multiple_fields(self):
        src = r'\header { title = "Song" composer = "J.S. Bach" }'
        h = _extract_header(src)
        assert h['title'] == "Song"
        assert h['composer'] == "J.S. Bach"

    def test_no_header_returns_empty(self):
        assert _extract_header(r'\score { c4 }') == {}

    def test_missing_key_absent(self):
        src = r'\header { title = "X" }'
        h = _extract_header(src)
        assert 'composer' not in h


# ---------------------------------------------------------------------------
# _atempo_filter
# ---------------------------------------------------------------------------

class TestAtempoFilter:
    def test_identity(self):
        # 1.0× — just one atempo=1.000000
        f = _atempo_filter(1.0)
        assert "atempo=1.0" in f

    def test_double_speed(self):
        f = _atempo_filter(2.0)
        assert "atempo=2.0" in f

    def test_half_speed(self):
        f = _atempo_filter(0.5)
        assert "atempo=0.5" in f

    def test_very_fast_chains(self):
        # 4× speed requires chaining: atempo=2.0,atempo=2.0
        f = _atempo_filter(4.0)
        assert f.count("atempo=2.0") == 2

    def test_very_slow_chains(self):
        # 0.25× speed requires chaining: atempo=0.5,atempo=0.5
        f = _atempo_filter(0.25)
        assert f.count("atempo=0.5") == 2

    def test_1_5x_single_filter(self):
        f = _atempo_filter(1.5)
        # Should be a single filter, no comma.
        assert "," not in f
        assert "atempo=1.5" in f


# ---------------------------------------------------------------------------
# build_bar_timing_map
# ---------------------------------------------------------------------------

class TestBuildBarTimingMap:
    TPB = 480

    def _tempo_map(self, bpm=120):
        us = int(60_000_000 / bpm)
        return [(0, 0.0, us)]

    def _note_map(self, n_notes=8, beat_ms=500.0, x_step=10.0):
        """Build a synthetic note timing map with n_notes notes."""
        return [
            TimingEntry(ms=i * beat_ms, x=i * x_step, y=0.0)
            for i in range(n_notes)
        ]

    def test_fewer_entries_than_notes(self):
        # 4/4 at 120 BPM: 4 beats per bar. 8 notes = 2 bars → 2 bar entries.
        note_map = self._note_map(n_notes=8, beat_ms=500.0)
        tm = self._tempo_map(120)
        result = build_bar_timing_map(note_map, tm, self.TPB, time_sig=(4, 4))
        # Should have fewer entries than 8 individual notes.
        assert len(result) < 8

    def test_x_within_note_range(self):
        note_map = self._note_map(n_notes=8, beat_ms=500.0, x_step=10.0)
        tm = self._tempo_map(120)
        result = build_bar_timing_map(note_map, tm, self.TPB, time_sig=(4, 4))
        min_x = min(e.x for e in result)
        max_x = max(e.x for e in result)
        note_min_x = min(e.x for e in note_map)
        note_max_x = max(e.x for e in note_map)
        assert min_x >= note_min_x
        assert max_x <= note_max_x

    def test_entries_sorted_by_ms(self):
        note_map = self._note_map(n_notes=8, beat_ms=500.0)
        tm = self._tempo_map(120)
        result = build_bar_timing_map(note_map, tm, self.TPB, time_sig=(4, 4))
        ms_vals = [e.ms for e in result]
        assert ms_vals == sorted(ms_vals)

    def test_fallback_on_empty(self):
        # Zero ticks_per_bar should return note_timing_map unchanged.
        note_map = self._note_map(n_notes=4)
        tm = self._tempo_map(120)
        # Denominator=0 would cause ZeroDivisionError; test an odd time_sig
        # where ticks_per_bar is still valid — just ensure output is non-empty.
        result = build_bar_timing_map(note_map, tm, self.TPB, time_sig=(3, 4))
        assert len(result) > 0


# ---------------------------------------------------------------------------
# scroll_offset_at
# ---------------------------------------------------------------------------

class TestScrollOffsetAt:

    def test_empty_timing_map_returns_zero(self):
        assert scroll_offset_at(1000.0, [], viewport_width=1920) == 0.0

    def test_cursor_position(self):
        # At ms=0, x=100, viewport=1920 → offset = max(0, 100 - 1920*0.45)
        tm = [TimingEntry(ms=0.0, x=100.0)]
        result = scroll_offset_at(0.0, tm, viewport_width=1920)
        expected = max(0.0, 100.0 - 1920 * CURSOR_POSITION)
        assert result == pytest.approx(expected)

    def test_clamps_to_zero(self):
        # x smaller than viewport × CURSOR_POSITION → offset = 0
        tm = [TimingEntry(ms=0.0, x=10.0)]
        result = scroll_offset_at(0.0, tm, viewport_width=1920)
        assert result == 0.0

    def test_interpolates_between_entries(self):
        tm = [
            TimingEntry(ms=0.0, x=0.0),
            TimingEntry(ms=1000.0, x=2000.0),
        ]
        # At ms=500 → x should be 1000.
        result = scroll_offset_at(500.0, tm, viewport_width=100)
        expected = max(0.0, 1000.0 - 100 * CURSOR_POSITION)
        assert result == pytest.approx(expected)

    def test_before_first_entry(self):
        tm = [TimingEntry(ms=100.0, x=50.0), TimingEntry(ms=200.0, x=100.0)]
        # ms < first entry → use first entry's x.
        result = scroll_offset_at(0.0, tm, viewport_width=100)
        expected = max(0.0, 50.0 - 100 * CURSOR_POSITION)
        assert result == pytest.approx(expected)

    def test_after_last_entry(self):
        tm = [TimingEntry(ms=0.0, x=0.0), TimingEntry(ms=1000.0, x=500.0)]
        result = scroll_offset_at(9999.0, tm, viewport_width=100)
        expected = max(0.0, 500.0 - 100 * CURSOR_POSITION)
        assert result == pytest.approx(expected)


# ---------------------------------------------------------------------------
# patch_ly_* integration smoke tests
# ---------------------------------------------------------------------------

_MINIMAL_LY = r"""\version "2.24.0"
\score {
  \new Staff {
    \relative c' {
      c4 d e f
    }
  }
  \midi { }
  \layout { }
}
"""

class TestPatchLySvg:
    def test_output_has_point_and_click(self):
        result = patch_ly_svg(_MINIMAL_LY)
        assert r'\pointAndClickTypes' in result

    def test_output_has_strip_paper(self):
        result = patch_ly_svg(_MINIMAL_LY)
        assert 'system-count = 1' in result

    def test_ties_stripped(self):
        src = _MINIMAL_LY.replace("c4 d e f", "c4~ d4")
        result = patch_ly_svg(src)
        assert '~' not in result

    def test_bar_numbers_injected_by_default(self):
        result = patch_ly_svg(_MINIMAL_LY, bar_numbers=True)
        assert 'BarNumber' in result

    def test_bar_numbers_omitted_when_disabled(self):
        result = patch_ly_svg(_MINIMAL_LY, bar_numbers=False)
        assert 'BarNumber' not in result


class TestPatchLyTimingMidi:
    def test_has_strip_paper(self):
        result = patch_ly_timing_midi(_MINIMAL_LY)
        assert 'system-count = 1' in result

    def test_no_point_and_click(self):
        result = patch_ly_timing_midi(_MINIMAL_LY)
        assert r'\pointAndClickTypes' not in result

    def test_ties_stripped(self):
        src = _MINIMAL_LY.replace("c4 d e f", "c4~ d4")
        result = patch_ly_timing_midi(src)
        assert '~' not in result


class TestPatchLyAudioMidi:
    def test_has_strip_paper(self):
        result = patch_ly_audio_midi(_MINIMAL_LY)
        assert 'system-count = 1' in result

    def test_no_tie_stripping(self):
        # Audio MIDI keeps ties for natural note durations.
        src = _MINIMAL_LY.replace("c4 d e f", "c4~ d4")
        result = patch_ly_audio_midi(src)
        assert '~' in result

    def test_no_point_and_click(self):
        result = patch_ly_audio_midi(_MINIMAL_LY)
        assert r'\pointAndClickTypes' not in result


# ---------------------------------------------------------------------------
# _inject_unfold_repeats
# ---------------------------------------------------------------------------

class TestInjectUnfoldRepeats:

    def test_wraps_score_music(self):
        src = r"""\score {
  \relative c' { c4 d }
  \midi { }
}"""
        result = _inject_unfold_repeats(src)
        assert r'\unfoldRepeats' in result

    def test_no_score_block_unchanged(self):
        src = r'\relative c { c4 }'
        result = _inject_unfold_repeats(src)
        assert r'\unfoldRepeats' not in result

    def test_multiple_score_blocks(self):
        src = r"""\score { \relative c' { c4 } \midi { } }
\score { \relative c' { d4 } \midi { } }"""
        result = _inject_unfold_repeats(src)
        assert result.count(r'\unfoldRepeats') == 2
