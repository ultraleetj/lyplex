#!/usr/bin/env python3
"""
verify_sync.py — verify lyplex metronome click/scroll sync.

Compiles timing MIDI, synthesizes click WAV, detects click burst onsets,
then compares detected positions to expected beat times. Reports per-beat
error in ms and frames so sync quality is quantified without visual review.

Usage:
    python verify_sync.py examples/score.ly [--count-in BARS] [--fps FPS]
    python verify_sync.py --midi path/to/timing.mid [--count-in BARS] [--fps FPS]
"""
from __future__ import annotations

import argparse
import array
import sys
import tempfile
import wave
from pathlib import Path

from lyplex_tool import (
    _CLICK_PRE_ROLL_MS,
    _tick_to_ms,
    compile_timing_midi,
    extract_timing_midi,
    render_click_wav,
)

LILYPOND = r"C:\Program Files\lilypond-2.24.4\bin\lilypond.exe"

# ---------------------------------------------------------------------------
# Click onset detection
# ---------------------------------------------------------------------------

def _find_click_onsets(wav_path: Path, threshold_ratio: float = 0.25, gap_ms: float = 40.0) -> list[float]:
    """Return click burst onset times (ms) from a mono or stereo WAV."""
    with wave.open(str(wav_path), "r") as wf:
        nch = wf.getnchannels()
        sr  = wf.getframerate()
        sw  = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())

    if sw == 2:
        samples = array.array("h", raw)
    elif sw == 4:
        samples = array.array("i", raw)
    else:
        raise ValueError(f"Unsupported sample width: {sw}")

    # mix down to mono
    if nch > 1:
        mono = [sum(samples[i : i + nch]) / nch for i in range(0, len(samples), nch)]
    else:
        mono = list(samples)

    peak = max(abs(s) for s in mono) or 1
    thresh = peak * threshold_ratio
    gap_samp = int(gap_ms / 1000.0 * sr)

    onsets: list[float] = []
    in_burst = False
    burst_start = 0
    last_high = -(gap_samp * 2)

    for i, s in enumerate(mono):
        if abs(s) >= thresh:
            if not in_burst:
                in_burst = True
                burst_start = i
            last_high = i
        elif in_burst and (i - last_high) > gap_samp:
            in_burst = False
            onsets.append(burst_start / sr * 1000.0)

    if in_burst:
        onsets.append(burst_start / sr * 1000.0)

    return onsets


# ---------------------------------------------------------------------------
# Expected beat times
# ---------------------------------------------------------------------------

def _beat_times(tempo_map, ticks_per_beat: int, last_tick: int) -> list[float]:
    """Compute expected beat onset times (ms) from tick 0 to last_tick."""
    times: list[float] = []
    t = 0
    while t <= last_tick + ticks_per_beat:
        ms = _tick_to_ms(t, tempo_map, ticks_per_beat)
        times.append(ms)
        t += ticks_per_beat
    return times


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Verify lyplex click/scroll sync")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("ly_file", nargs="?", help=".ly source file (compiles timing MIDI)")
    src.add_argument("--midi", metavar="MIDI", help="pre-compiled timing MIDI (skips LilyPond)")
    ap.add_argument("--count-in", type=int, default=1, metavar="BARS")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--threshold", type=float, default=0.25, metavar="RATIO",
                    help="click onset threshold as fraction of peak (default 0.25)")
    args = ap.parse_args()

    fps = args.fps
    frame_ms = 1000.0 / fps
    count_in_bars = args.count_in

    with tempfile.TemporaryDirectory(prefix="lyplex_verify_") as wd:

        # --- get timing MIDI ---
        if args.midi:
            midi_path = Path(args.midi)
            print(f"[verify] using MIDI: {midi_path}")
        else:
            ly_path = Path(args.ly_file)
            source = ly_path.read_text(encoding="utf-8")
            print("[verify] compiling timing MIDI...")
            midi_path = compile_timing_midi(source, wd, lilypond_exe=LILYPOND)

        # --- parse MIDI ---
        print("[verify] parsing timing MIDI...")
        note_ons, tempo_map, ticks_per_beat, time_sig = extract_timing_midi(midi_path)

        last_tick = max(e[0] for e in note_ons)
        beat_ms_list = _beat_times(tempo_map, ticks_per_beat, last_tick)
        total_ms = beat_ms_list[-1] + 2000.0

        # --- synthesize click WAV ---
        print("[verify] synthesizing click WAV...")
        click_wav = Path(wd) / "click.wav"
        click_result = render_click_wav(
            tempo_map, ticks_per_beat, time_sig,
            total_ms=total_ms,
            out_path=click_wav,
            count_in_bars=count_in_bars,
        )
        count_in_ms = click_result.count_in_ms
        count_in_music_ms = count_in_ms - _CLICK_PRE_ROLL_MS

        print(f"[verify] count_in_ms    = {count_in_ms:.3f} ms")
        print(f"[verify] pre_roll       = {_CLICK_PRE_ROLL_MS:.1f} ms")
        print(f"[verify] count_in_music = {count_in_music_ms:.3f} ms")

        # --- detect onsets ---
        print("[verify] detecting click onsets in WAV...")
        onsets = _find_click_onsets(click_wav, threshold_ratio=args.threshold)
        print(f"[verify] detected {len(onsets)} onsets")

        # separate count-in vs music onsets
        boundary = count_in_ms - frame_ms
        countin_onsets = [t for t in onsets if t < boundary]
        music_onsets   = [t for t in onsets if t >= boundary]

        # --- count-in report ---
        ticks_per_bar = ticks_per_beat * time_sig[0] * 4 // time_sig[1]
        n_expected_countin = count_in_bars * time_sig[0]  # beats per bar × bars
        print(f"\n{'='*62}")
        print(f" COUNT-IN  (expected {n_expected_countin} beats, {count_in_bars} bar(s))")
        print(f"{'='*62}")
        print(f"  {'#':>3}  {'detected_ms':>11}  {'expected_ms':>11}  {'delta':>7}  {'frames':>7}")
        print(f"  {'-'*3}  {'-'*11}  {'-'*11}  {'-'*7}  {'-'*7}")

        ci_errors: list[float] = []
        for k, onset_ms in enumerate(countin_onsets):
            # count-in beat k (0-indexed from first count-in beat)
            t_ticks = (count_in_bars - k // time_sig[0]) * ticks_per_bar - (k % time_sig[0]) * ticks_per_beat
            exp_ms = count_in_music_ms - _tick_to_ms(t_ticks, tempo_map, ticks_per_beat) + _CLICK_PRE_ROLL_MS
            delta = onset_ms - exp_ms
            ci_errors.append(delta)
            print(f"  {k+1:>3}  {onset_ms:>11.2f}  {exp_ms:>11.2f}  {delta:>+7.2f}  {delta/frame_ms:>+7.3f}")

        # --- music beats report ---
        print(f"\n{'='*70}")
        print(f" MUSIC BEATS  (first {min(len(music_onsets), len(beat_ms_list))} of {len(beat_ms_list)} beats vs click WAV)")
        print(f"{'='*70}")
        print(f"  {'beat':>5}  {'detected_ms':>11}  {'expected_ms':>11}  {'delta_ms':>9}  {'frames':>7}  status")
        print(f"  {'-'*5}  {'-'*11}  {'-'*11}  {'-'*9}  {'-'*7}  ------")

        errors: list[float] = []
        n = min(len(music_onsets), len(beat_ms_list))
        for i in range(n):
            onset_ms = music_onsets[i]
            expected_ms = beat_ms_list[i] + count_in_ms   # click position in WAV
            delta = onset_ms - expected_ms
            frames = delta / frame_ms
            status = "ok" if abs(frames) <= 1.0 else "WARN" if abs(frames) <= 2.0 else "ERROR"
            errors.append(delta)
            print(f"  {i+1:>5}  {onset_ms:>11.2f}  {expected_ms:>11.2f}  {delta:>+9.3f}  {frames:>+7.4f}  {status}")

        # --- summary ---
        print(f"\n{'='*62}")
        print(f" SUMMARY")
        print(f"{'='*62}")
        print(f"  fps            : {fps}")
        print(f"  frame duration : {frame_ms:.4f} ms")
        print(f"  beats checked  : {len(errors)}")

        if errors:
            mean_err = sum(errors) / len(errors)
            max_err  = max(abs(e) for e in errors)
            print(f"  mean error     : {mean_err:+.4f} ms")
            print(f"  max  error     : {max_err:.4f} ms  ({max_err/frame_ms:.4f} frames)")
            ok = sum(1 for e in errors if abs(e) / frame_ms <= 1.0)
            warn = sum(1 for e in errors if 1.0 < abs(e) / frame_ms <= 2.0)
            bad  = sum(1 for e in errors if abs(e) / frame_ms > 2.0)
            print(f"  within 1 frame : {ok}/{len(errors)}")
            print(f"  within 2 frames: {ok+warn}/{len(errors)}")
            print(f"  > 2 frames     : {bad}/{len(errors)}")

            if bad == 0 and warn == 0:
                print("\n  RESULT: PASS — all beats within 1 frame")
            elif bad == 0:
                print(f"\n  RESULT: MARGINAL — {warn} beat(s) between 1-2 frames")
            else:
                print(f"\n  RESULT: FAIL — {bad} beat(s) exceed 2 frames")
        else:
            print("  (no music beats to compare)")


if __name__ == "__main__":
    main()
