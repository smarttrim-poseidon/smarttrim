"""SmartTrim sensor recordings: one CSV format for export and reload.

Hardware-independent. The Arduino sketch prints timestamp_ms,roll_deg,pitch_deg
at 115200 baud (timestamp_ms = Arduino millis()). arduino_serial.parse_sensor_line
turns each line into a dict; this module adds run metadata, a consistent elapsed
time_s, and loads the same CSV back for the Recorded view.
"""
import io
import math

import pandas as pd

from calculations import (
    WEIGHING_ELECTRONICS_INCLUDED,
    WEIGHING_ELECTRONICS_SEPARATE,
    normalise_weighing_basis,
)

TIME_SERIES_COLUMNS = [
    "time_s", "timestamp_ms", "recorded_at_utc", "roll_deg", "pitch_deg"
]
METADATA_COLUMNS = [
    "run_id", "source", "cad_version", "water_condition", "mooring_setup",
    "cargo_preset", "load_g", "base_mass_g", "cargo_x_midship_mm",
    "cargo_y_mm", "cargo_z_mm", "coordinate_origin", "axis_convention",
    "notes", "sensor_file_reference",
    # Added with the dry-base weighing basis; older CSVs without them load as
    # "not_recorded" with blank electronics values.
    "base_weighing_basis", "electronics_mass_g", "electronics_x_midship_mm",
    "electronics_y_mm", "electronics_z_mm",
    # Test metadata only (not used by any calculation); older CSVs load it blank.
    "tank_water_depth_m",
]
EXPORT_COLUMNS = METADATA_COLUMNS[:2] + TIME_SERIES_COLUMNS + METADATA_COLUMNS[2:]

# Sources that are measured. Anything else (simulated, test, synthetic) is not.
MEASURED_SOURCES = {"arduino_mpu6050"}


def build_export_frame(rows, metadata):
    """Rows from the live reader (or the simulator) plus run metadata -> export frame.

    rows: dicts with roll_deg, pitch_deg and either timestamp_ms or time_s; the
    original timestamp_ms and recorded_at_utc are preserved when present.
    metadata: dict with any of METADATA_COLUMNS; source defaults per row.
    """
    df = pd.DataFrame(list(rows))
    if df.empty:
        return pd.DataFrame(columns=EXPORT_COLUMNS)
    for col in TIME_SERIES_COLUMNS:
        if col not in df.columns:
            df[col] = None
    timestamps = pd.to_numeric(df["timestamp_ms"], errors="coerce")
    if timestamps.notna().any():
        df["time_s"] = (timestamps - timestamps.dropna().iloc[0]) / 1000.0
    for col in METADATA_COLUMNS:
        value = metadata.get(col)
        if col == "source" and "source" in df.columns and value is None:
            continue
        df[col] = value
    return df[EXPORT_COLUMNS]


def export_csv_bytes(frame):
    return frame.to_csv(index=False).encode("utf-8")


def load_recording(file_or_text):
    """Load an exported CSV (or an older CSV that already has time_s).

    Returns (frame, problems). frame has numeric time_s/roll_deg/pitch_deg and
    every metadata column (blank if absent). Older files without time_s but with
    timestamp_ms get time_s derived from timestamp_ms.
    """
    if isinstance(file_or_text, bytes):
        file_or_text = io.BytesIO(file_or_text)
    elif isinstance(file_or_text, str):
        file_or_text = io.StringIO(file_or_text)
    df = pd.read_csv(file_or_text)
    problems = []
    for col in ("roll_deg", "pitch_deg"):
        if col not in df.columns:
            problems.append(f"missing column {col}")
    timestamps = (pd.to_numeric(df["timestamp_ms"], errors="coerce")
                  if "timestamp_ms" in df.columns else None)
    if timestamps is not None and timestamps.notna().any():
        df["time_s"] = (timestamps - timestamps.dropna().iloc[0]) / 1000.0
    elif "time_s" not in df.columns:
        problems.append("missing column time_s (and no timestamp_ms to derive it)")
    if problems:
        return None, problems
    for col in ("time_s", "roll_deg", "pitch_deg"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in METADATA_COLUMNS + ["timestamp_ms", "recorded_at_utc"]:
        if col not in df.columns:
            df[col] = None
    if "configuration" in df.columns and df["configuration"].isna().all():
        df["configuration"] = None
    df["run_id"] = df["run_id"].fillna("unnamed run").astype(str)
    df["source"] = df["source"].fillna("unknown source").astype(str)
    df["base_weighing_basis"] = df["base_weighing_basis"].map(normalise_weighing_basis)
    df["tank_water_depth_m"] = pd.to_numeric(df["tank_water_depth_m"], errors="coerce")
    df = df.dropna(subset=["time_s", "roll_deg"]).sort_values(["run_id", "time_s"])
    if df.empty:
        problems.append("no valid rows")
        return None, problems
    return df.reset_index(drop=True), problems


def format_measure(value, unit):
    """A value for display; blank, NaN or non-numeric -> 'not recorded'."""
    number = pd.to_numeric(value, errors="coerce")
    return "not recorded" if pd.isna(number) else f"{float(number):g} {unit}"


def format_grams(value):
    return format_measure(value, "g")


def describe_cargo_position(cargo_preset, x_mm, y_mm, z_mm):
    """Cargo X/Y/Z for display; base-only runs have no cargo position."""
    if str(cargo_preset).strip() == "Base only":
        return "Cargo position: none (base only)"
    return ("Cargo position from midship: "
            f"X {format_measure(x_mm, 'mm')}, Y {format_measure(y_mm, 'mm')}, "
            f"Z {format_measure(z_mm, 'mm')}")


def describe_weighing(basis, base_mass_g, electronics_mass_g):
    """Plain-language dry-base weighing metadata for one recording."""
    basis = normalise_weighing_basis(basis)
    base = f"Dry base mass: {format_grams(base_mass_g)}"
    if basis == WEIGHING_ELECTRONICS_INCLUDED:
        return base + " · Electronics included in the dry base mass"
    electronics = f"Electronics mass: {format_grams(electronics_mass_g)}"
    if basis == WEIGHING_ELECTRONICS_SEPARATE:
        return f"{base} · Electronics weighed separately · {electronics}"
    return f"{base} · Weighing basis: not recorded · {electronics}"


def is_measured(source):
    return str(source).strip() in MEASURED_SOURCES


def motion_stats(frame):
    """Max |roll| and |pitch| plus signed min/max in degrees; None when unavailable."""
    def stats(col):
        if frame is None or col not in frame.columns:
            return {"max_abs": None, "min": None, "max": None}
        s = pd.to_numeric(frame[col], errors="coerce").dropna()
        s = s[s.map(math.isfinite)]
        if s.empty:
            return {"max_abs": None, "min": None, "max": None}
        return {"max_abs": float(s.abs().max()), "min": float(s.min()), "max": float(s.max())}
    return {"roll_deg": stats("roll_deg"), "pitch_deg": stats("pitch_deg"),
            "samples": 0 if frame is None else int(len(frame))}


def simulated_rows(roll_amplitude_deg, pitch_offset_deg, seconds=12, rate_hz=10):
    """Synthetic trace for demos and tests. Always labelled source='simulated'."""
    rows = []
    for i in range(int(seconds * rate_hz)):
        t = i / rate_hz
        rows.append({"time_s": t, "timestamp_ms": None, "recorded_at_utc": None,
                     "roll_deg": roll_amplitude_deg * math.sin(2 * math.pi * t / 4.0),
                     "pitch_deg": pitch_offset_deg, "source": "simulated"})
    return rows
