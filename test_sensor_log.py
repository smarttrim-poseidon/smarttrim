import pandas as pd

from sensor_log import (
    build_export_frame,
    describe_cargo_position,
    describe_weighing,
    export_csv_bytes,
    format_grams,
    load_recording,
    motion_stats,
)


def test_weighing_caption_never_shows_nan():
    assert describe_weighing("electronics_included", 330.0, float("nan")) == (
        "Dry base mass: 330 g · Electronics included in the dry base mass")
    assert describe_weighing("electronics_separate", 300.0, 29.8) == (
        "Dry base mass: 300 g · Electronics weighed separately · Electronics mass: 29.8 g")
    assert describe_weighing("electronics_separate", 300.0, None) == (
        "Dry base mass: 300 g · Electronics weighed separately · "
        "Electronics mass: not recorded")
    assert describe_weighing(float("nan"), float("nan"), float("nan")) == (
        "Dry base mass: not recorded · Weighing basis: not recorded · "
        "Electronics mass: not recorded")
    for blank in (None, float("nan"), "", "abc"):
        assert format_grams(blank) == "not recorded"
    assert format_grams(0) == "0 g"
    assert describe_cargo_position("Base only", float("nan"), None, None) == (
        "Cargo position: none (base only)")
    assert describe_cargo_position("250 g", -20.0, 0.0, float("nan")) == (
        "Cargo position from midship: X -20 mm, Y 0 mm, Z not recorded")


def test_live_format_export_reloads_with_original_timestamps_and_metadata():
    rows = [
        {"timestamp_ms": 1250, "recorded_at_utc": "2026-11-21T09:00:00+00:00",
         "roll_deg": 1.5, "pitch_deg": -0.5},
        {"timestamp_ms": 1300, "recorded_at_utc": "2026-11-21T09:00:00.050+00:00",
         "roll_deg": -3.0, "pitch_deg": 2.0},
        {"timestamp_ms": 1350, "recorded_at_utc": "2026-11-21T09:00:00.100+00:00",
         "roll_deg": 2.0, "pitch_deg": -4.5},
    ]
    metadata = {
        "run_id": "RUN_TEST",
        "source": "arduino_mpu6050",
        "cad_version": "V5",
        "water_condition": "still freshwater",
        "mooring_setup": "port/starboard crossbeam lines (slack)",
        "cargo_preset": "150 g · centre",
        "load_g": 150,
        "base_mass_g": 308.1,
        "cargo_x_midship_mm": 0,
        "cargo_y_mm": 0,
        "cargo_z_mm": None,
        "coordinate_origin": "midship",
        "axis_convention": "bench mapping pending",
        "notes": "offline round trip",
        "sensor_file_reference": "sensor.csv",
    }

    frame = build_export_frame(rows, metadata)
    frame["time_s"] = [91, 92, 93]
    restored, problems = load_recording(export_csv_bytes(frame))

    assert problems == []
    assert restored["timestamp_ms"].tolist() == [1250, 1300, 1350]
    assert restored["time_s"].tolist() == [0.0, 0.05, 0.1]
    assert restored["recorded_at_utc"].tolist() == [
        row["recorded_at_utc"] for row in rows
    ]
    assert restored["run_id"].unique().tolist() == ["RUN_TEST"]
    assert restored["source"].unique().tolist() == ["arduino_mpu6050"]
    assert restored["mooring_setup"].unique().tolist() == [
        "port/starboard crossbeam lines (slack)"
    ]
    assert restored["cargo_x_midship_mm"].iloc[0] == 0
    assert motion_stats(restored)["roll_deg"] == {
        "max_abs": 3.0, "min": -3.0, "max": 2.0
    }
    assert motion_stats(restored)["pitch_deg"] == {
        "max_abs": 4.5, "min": -4.5, "max": 2.0
    }


def test_recorded_csv_without_timestamp_ms_keeps_elapsed_time():
    csv = (
        "run_id,source,time_s,roll_deg,pitch_deg\n"
        "RUN_OLD,recorded,0.0,0.5,1.0\n"
        "RUN_OLD,recorded,0.2,-1.5,2.0\n"
    )
    restored, problems = load_recording(csv)
    assert problems == []
    assert restored["time_s"].tolist() == [0.0, 0.2]


def test_missing_recording_is_unavailable_not_zero():
    stats = motion_stats(None)
    assert stats["samples"] == 0
    assert stats["roll_deg"] == {"max_abs": None, "min": None, "max": None}
    restored, problems = load_recording(
        pd.DataFrame({"run_id": ["RUN"], "source": ["recorded"],
                      "time_s": [0.0], "pitch_deg": [1.0]}).to_csv(index=False)
    )
    assert restored is None and problems == ["missing column roll_deg"]


def test_weighing_metadata_round_trips_in_sensor_csv():
    metadata = {"run_id": "RUN_E", "source": "arduino_mpu6050", "base_mass_g": 300.0,
                "base_weighing_basis": "electronics_separate", "electronics_mass_g": 29.8,
                "electronics_x_midship_mm": 0.0, "electronics_y_mm": None,
                "electronics_z_mm": 70.0}
    frame = build_export_frame([{"timestamp_ms": 10, "roll_deg": 0.1, "pitch_deg": 0.2}],
                               metadata)
    restored, problems = load_recording(export_csv_bytes(frame))
    assert problems == []
    row = restored.iloc[0]
    assert row["base_weighing_basis"] == "electronics_separate"
    assert row["base_mass_g"] == 300.0 and row["electronics_mass_g"] == 29.8
    assert row["electronics_z_mm"] == 70.0 and pd.isna(row["electronics_y_mm"])


def test_older_sensor_csv_replays_with_unknown_weighing_basis():
    # Columns exported before the weighing basis existed (V5 integration, f115d3b).
    old_row = {"run_id": "RUN_OLD", "source": "arduino_mpu6050", "time_s": 0.0,
               "timestamp_ms": 3712, "recorded_at_utc": "", "roll_deg": 0.004,
               "pitch_deg": -0.011, "cad_version": "V5 SLEEK", "water_condition": "still",
               "mooring_setup": "Port/starboard", "cargo_preset": "150 g", "load_g": 150,
               "base_mass_g": 330, "cargo_x_midship_mm": 0, "cargo_y_mm": 0,
               "cargo_z_mm": "", "coordinate_origin": "midship",
               "axis_convention": "pending", "notes": "", "sensor_file_reference": "s.csv"}
    second = {**old_row, "timestamp_ms": 3732, "roll_deg": 0.006, "pitch_deg": -0.009}
    csv = (",".join(old_row) + "\n"
           + "\n".join(",".join(str(v) for v in r.values()) for r in (old_row, second)) + "\n")
    restored, problems = load_recording(csv)
    assert problems == [] and len(restored) == 2
    assert restored["time_s"].tolist() == [0.0, 0.02]
    assert set(restored["base_weighing_basis"]) == {"not_recorded"}
    for col in ("electronics_mass_g", "electronics_x_midship_mm", "electronics_y_mm",
                "electronics_z_mm", "tank_water_depth_m"):
        assert restored[col].isna().all()
    assert restored["base_mass_g"].iloc[0] == 330


def test_tank_water_depth_round_trips_and_stays_blank_when_not_measured():
    rows = [{"timestamp_ms": 10, "roll_deg": 0.1, "pitch_deg": 0.2}]
    measured = build_export_frame(rows, {"run_id": "T400_01", "source": "arduino_mpu6050",
                                         "cargo_preset": "400 g", "load_g": 400.0,
                                         "tank_water_depth_m": 0.3})
    restored, problems = load_recording(export_csv_bytes(measured))
    assert problems == [] and restored["tank_water_depth_m"].iloc[0] == 0.3
    assert restored["cargo_preset"].iloc[0] == "400 g"
    blank = build_export_frame(rows, {"run_id": "T400_02", "source": "arduino_mpu6050"})
    restored, problems = load_recording(export_csv_bytes(blank))
    assert problems == [] and pd.isna(restored["tank_water_depth_m"].iloc[0])
    # Exported between the weighing-basis change and this one: no depth column.
    without_depth = export_csv_bytes(measured.drop(columns=["tank_water_depth_m"]))
    restored, problems = load_recording(without_depth)
    assert problems == [] and pd.isna(restored["tank_water_depth_m"].iloc[0])
