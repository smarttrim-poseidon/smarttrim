"""Write demo/samples/simulated_motion_sample.csv in the SmartTrim sensor CSV format.

Every row is source = "simulated" (never measured). It contains three recordings:
- SIM_PITCH_ONLY: pitch varies, roll stays 0 (the bow should rise and fall);
- SIM_ROLL_ONLY: roll varies, pitch stays 0 (the boat should tilt sideways);
- SIM_COMBINED_GAP: both vary, with a deliberate 1 s gap (no samples) that the
  replay must show as missing, not fill in.
Uses the dashboard's own sensor_log.build_export_frame so the columns match exactly.
"""
import math
import sys
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO_DIR.parent))
import pandas as pd  # noqa: E402

from sensor_log import build_export_frame, export_csv_bytes  # noqa: E402

RATE_HZ = 10
SECONDS = 8.0
OUTPUT = DEMO_DIR / "samples" / "simulated_motion_sample.csv"


def _rows(roll_fn, pitch_fn, skip=None):
    rows = []
    for i in range(int(SECONDS * RATE_HZ) + 1):
        t = round(i / RATE_HZ, 3)
        if skip and skip[0] <= t < skip[1]:
            continue
        rows.append({"time_s": t, "timestamp_ms": None, "recorded_at_utc": None,
                     "roll_deg": round(roll_fn(t), 3), "pitch_deg": round(pitch_fn(t), 3)})
    return rows


def build():
    def wave(amplitude, period):
        return lambda t: amplitude * math.sin(2 * math.pi * t / period)

    def zero(_t):
        return 0.0

    recordings = [
        ("SIM_PITCH_ONLY", _rows(zero, wave(5.0, 4.0)),
         "SIMULATED demo sample: pitch only (+ = bow up), roll 0. Not measured."),
        ("SIM_ROLL_ONLY", _rows(wave(8.0, 4.0), zero),
         "SIMULATED demo sample: roll only (+ = starboard down), pitch 0. Not measured."),
        ("SIM_COMBINED_GAP", _rows(wave(6.0, 3.2), wave(3.0, 5.0), skip=(4.0, 5.0)),
         "SIMULATED demo sample: roll and pitch with a 1 s gap (4.0-5.0 s). Not measured."),
    ]
    frames = []
    for run_id, rows, note in recordings:
        frames.append(build_export_frame(rows, {
            "run_id": run_id, "source": "simulated", "cad_version": "V5 SLEEK",
            "water_condition": "simulated", "notes": note,
            "axis_convention": "demo convention: + roll = starboard down, + pitch = bow up",
        }))
    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(export_csv_bytes(build()))
    print(f"wrote {OUTPUT}")
