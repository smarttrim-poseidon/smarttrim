"""Offline-first SmartTrim V5 tank-test dashboard."""
from datetime import datetime, timezone

import pandas as pd
import serial
import streamlit as st

from alert_explainer import explain_alert
from arduino_serial import (
    available_ports,
    connect_arduino,
    is_arduino_connected,
    read_line,
    safe_disconnect,
)
from calculations import (
    V5_CARGO_PRESETS_G,
    V5_CORE_PRINT_MASS_G,
    V5_DRAFT_STATIONS_MIDSHIP_MM,
    V5_SEAM_HEIGHT_MM,
    WEIGHING_ELECTRONICS_INCLUDED,
    WEIGHING_ELECTRONICS_SEPARATE,
    WEIGHING_NOT_RECORDED,
    documented_dry_mass_g,
    draft_prediction_error,
    loading_match,
    loading_v5_weighed,
    tank_reading_summary,
    v5_cargo_preset,
    v5_upright_draft,
)
from sensor_log import (
    build_export_frame,
    describe_cargo_position,
    describe_weighing,
    export_csv_bytes,
    format_grams,
    format_measure,
    is_measured,
    load_recording,
    motion_stats,
    simulated_rows,
)


st.set_page_config(page_title="SmartTrim V5", page_icon="🚢", layout="wide")

if "run_records" not in st.session_state:
    st.session_state.run_records = []
if "live_connection" not in st.session_state:
    st.session_state.live_connection = None
if "live_recording" not in st.session_state:
    st.session_state.live_recording = False
if "live_rows" not in st.session_state:
    st.session_state.live_rows = []
if "live_latest" not in st.session_state:
    st.session_state.live_latest = None
if "live_status" not in st.session_state:
    st.session_state.live_status = None
if "run_id" not in st.session_state:
    st.session_state.run_id = datetime.now(timezone.utc).strftime("RUN_%Y%m%dT%H%M%SZ")


def _optional_float(value):
    if value is None or pd.isna(value):
        return None
    return float(value)


WEIGHING_LABELS = {
    "Electronics included": WEIGHING_ELECTRONICS_INCLUDED,
    "Electronics weighed separately": WEIGHING_ELECTRONICS_SEPARATE,
    "Not recorded": WEIGHING_NOT_RECORDED,
}


def _display(value, digits=1, suffix=" mm"):
    return "Unavailable" if value is None else f"{value:.{digits}f}{suffix}"


def _run_sensor_metadata(
    *,
    run_id,
    configuration,
    water_condition,
    mooring_setup,
    cargo_preset,
    cargo_mass_g,
    base_mass_g,
    cargo_x_mm,
    cargo_y_mm,
    cargo_z_mm,
    axis_convention,
    notes,
    sensor_file_reference,
    weighing_basis,
    electronics,
    tank_water_depth_m,
):
    return {
        "run_id": run_id,
        "source": None,
        "cad_version": configuration,
        "water_condition": water_condition,
        "mooring_setup": mooring_setup,
        "cargo_preset": cargo_preset,
        "load_g": cargo_mass_g,
        "base_mass_g": base_mass_g,
        "cargo_x_midship_mm": cargo_x_mm,
        "cargo_y_mm": cargo_y_mm,
        "cargo_z_mm": cargo_z_mm,
        "coordinate_origin": "midship; x=-100 stern, 0 midship, +100 bow",
        "axis_convention": axis_convention,
        "notes": notes,
        "sensor_file_reference": sensor_file_reference,
        "base_weighing_basis": weighing_basis,
        **electronics,
        "tank_water_depth_m": tank_water_depth_m,
    }


st.title("SmartTrim | V5 tank-test dashboard")
st.caption(
    "V5 is the primary printed configuration; V3 is retained as a fallback. "
    "This prototype is not a navigation or safety system."
)
st.warning(
    "Keep CAD estimates, manual tank readings, simulated traces, and sensor "
    "measurements distinct. No physical V5 or MPU6050 results are pre-filled."
)

with st.sidebar:
    st.header("Run setup")
    configuration = st.selectbox(
        "CAD configuration",
        ["V5 · 120 mm (primary)", "V3 (fallback; inputs unverified)"],
    )
    run_id = st.text_input("Run ID", key="run_id")
    water_condition = st.text_input(
        "Water / condition", value="Not recorded", key="water_condition"
    )
    water_density_kg_m3 = st.number_input(
        "Water density (kg/m³)",
        min_value=1.0,
        value=1000.0,
        step=1.0,
        help="1000 kg/m³ is the V5 curve reference freshwater density; enter a measured value if available.",
    )
    tank_water_depth_input = st.number_input(
        "Measured tank water depth (m), optional",
        min_value=0.0,
        value=None,
        step=0.01,
        key="tank_water_depth_m",
        help=(
            "Test metadata for this run, saved with the manual record and sensor CSV. "
            "Leave blank until measured. It is not used by the CAD draft estimate or "
            "the under-keel clearance alert."
        ),
    )
    tank_water_depth_m = _optional_float(tank_water_depth_input)
    mooring_setup = st.selectbox(
        "Slack mooring setup",
        [
            "Port/starboard lines to structural crossbeams (slack)",
            "Bow/stern symmetric crossbeam bridles (slack)",
        ],
    )
    st.caption(
        "Both setups use slack lines attached at the structural crossbeams. "
        "Propellers are outside this test scope."
    )
    assembled_base_mass_g = st.number_input(
        "Measured dry base mass (g)",
        min_value=0.0,
        value=None,
        step=1.0,
        key="assembled_base_mass_g",
        help=(
            "The dry assembled boat on the scale, without cargo. It includes the "
            "Nano, MPU6050 and wiring only if they were on the boat when weighed. "
            "Leave blank until weighed."
        ),
    )
    weighing_label = st.radio(
        "How was the dry base weighed?",
        list(WEIGHING_LABELS),
        index=2,
        key="base_weighing_basis",
        help=(
            "Electronics included: the Nano, MPU6050 and wiring were on the boat "
            "on the scale. Electronics weighed separately: they were off the boat "
            "and are entered below. Not recorded: total mass and CAD draft stay pending."
        ),
    )
    weighing_basis = WEIGHING_LABELS[weighing_label]
    if weighing_basis == WEIGHING_ELECTRONICS_SEPARATE:
        electronics_mass_g = st.number_input(
            "Measured electronics mass (g)",
            min_value=0.0,
            value=None,
            step=0.1,
            key="electronics_mass_g",
            help=(
                "Nano, MPU6050 and the wiring carried on the boat, weighed off the "
                "boat. Leave blank until weighed."
            ),
        )
    else:
        electronics_mass_g = None  # ignore any value left in session state
    st.caption(
        "Each mass is counted once: dry base (with or without electronics, as "
        "selected), plus separately weighed electronics if selected, plus one "
        "cargo block."
    )
    st.caption(
        f"Printed V5 core CAD mass: {V5_CORE_PRINT_MASS_G:.1f} g; nominal "
        "plastic-only CAD mass, not the assembled boat mass."
        if V5_CORE_PRINT_MASS_G is not None
        else "V5 core CAD mass unavailable because the attributed CAD data could not be loaded."
    )

st.subheader("1 · One active cargo block")
CARGO_CASES = ["Base only"] + [f"{mass:g} g" for mass in V5_CARGO_PRESETS_G]
st.caption(
    "Use base-only, then one cargo block at a time. The "
    + ", ".join(CARGO_CASES[1:])
    + " cases are alternatives, never summed. The case is a label; the "
    "calculation uses the weighed cargo mass you enter."
)
cargo_case = st.selectbox("Cargo case", CARGO_CASES, key="cargo_case")
if cargo_case == "Base only":
    cargo_mass_g = 0.0
    cargo_position = None
    cargo_x_midship_mm = cargo_y_mm = cargo_z_mm = None
    cargo_label = "Base only"
else:
    preset_mass_g = float(cargo_case.split()[0])
    cargo_mass_g = st.number_input(
        "Measured active cargo mass (g)",
        min_value=0.0,
        value=None,
        step=1.0,
        key=f"cargo_mass_{preset_mass_g:g}",
        help=f"{preset_mass_g:g} g is the selected case, not a measured mass. Enter the weighed active block mass.",
    )
    cargo_position = st.selectbox(
        "Cargo starting position",
        ["centre", "aft", "starboard", "custom"],
        key=f"cargo_position_{preset_mass_g:g}",
    )
    defaults = {
        "centre": (0.0, 0.0),
        "aft": (-20.0, 0.0),
        "starboard": (0.0, 20.0),
        "custom": (0.0, 0.0),
    }
    x_default, y_default = defaults[cargo_position]
    x_col, y_col, z_col = st.columns(3)
    cargo_x_midship_mm = x_col.number_input(
        "Cargo X from midship (mm)",
        value=x_default,
        step=1.0,
        key=f"cargo_x_{preset_mass_g:g}_{cargo_position}",
        help="Positive X points toward the bow.",
    )
    cargo_y_mm = y_col.number_input(
        "Cargo Y from centreline (mm)",
        value=y_default,
        step=1.0,
        key=f"cargo_y_{preset_mass_g:g}_{cargo_position}",
        help="Positive Y points toward starboard.",
    )
    cargo_z_mm = z_col.number_input(
        "Cargo Z from hull bottom (mm)",
        min_value=0.0,
        value=None,
        step=1.0,
        key=f"cargo_z_{preset_mass_g:g}_{cargo_position}",
        help="Leave blank until the cargo centre height is measured.",
    )
    if cargo_position == "custom":
        cargo_label = "custom"
    else:
        cargo_label = cargo_position

st.caption(
    "Cargo X is midpoint-based: stern −100 mm, midship 0 mm, bow +100 mm. "
    "Y is positive to starboard; Z is upward from the hull bottom."
)

base_com_col1, base_com_col2, base_com_col3 = st.columns(3)
base_x_midship_mm = base_com_col1.number_input(
    "Measured assembled-base COM X from midship (mm)",
    value=None,
    step=1.0,
    key="base_com_x",
)
base_y_mm = base_com_col2.number_input(
    "Measured assembled-base COM Y from centreline (mm)",
    value=None,
    step=1.0,
    key="base_com_y",
)
base_z_mm = base_com_col3.number_input(
    "Measured assembled-base COM Z from hull bottom (mm)",
    value=None,
    step=1.0,
    key="base_com_z",
)
st.caption(
    "Base centre-of-mass inputs remain blank until measured, and use the same "
    "boat that was weighed: with the electronics on board if \"Electronics "
    "included\", without them if \"Electronics weighed separately\". The "
    "plastic-only CAD centre of mass excludes fasteners, sealant, electronics, "
    "motors, and batteries."
)

if weighing_basis == WEIGHING_ELECTRONICS_SEPARATE:
    elec_col1, elec_col2, elec_col3 = st.columns(3)
    electronics_x_mm = elec_col1.number_input(
        "Electronics COM X from midship (mm)", value=None, step=1.0, key="electronics_x"
    )
    electronics_y_mm = elec_col2.number_input(
        "Electronics COM Y from centreline (mm)", value=None, step=1.0, key="electronics_y"
    )
    electronics_z_mm = elec_col3.number_input(
        "Electronics COM Z from hull bottom (mm)",
        min_value=0.0, value=None, step=1.0, key="electronics_z",
    )
    st.caption(
        "Where the separately weighed Nano, MPU6050 and wiring sit on the boat. "
        "A blank coordinate only makes the matching centre (LCG, TCG or KG) unavailable."
    )
    electronics = {
        "electronics_mass_g": _optional_float(electronics_mass_g),
        "electronics_x_midship_mm": _optional_float(electronics_x_mm),
        "electronics_y_mm": _optional_float(electronics_y_mm),
        "electronics_z_mm": _optional_float(electronics_z_mm),
    }
else:
    # Included or not recorded: no separate electronics values are used or saved.
    electronics = {
        "electronics_mass_g": None,
        "electronics_x_midship_mm": None,
        "electronics_y_mm": None,
        "electronics_z_mm": None,
    }

base_item = {
    "name": "measured dry base",
    "mass_g": _optional_float(assembled_base_mass_g),
    "x_mm": _optional_float(base_x_midship_mm),
    "y_mm": _optional_float(base_y_mm),
    "z_mm": _optional_float(base_z_mm),
}
cargo_items = []
if cargo_case != "Base only":
    if cargo_position == "custom":
        cargo_item = {
            "name": "active cargo",
            "mass_g": _optional_float(cargo_mass_g),
            "x_mm": _optional_float(cargo_x_midship_mm),
            "y_mm": _optional_float(cargo_y_mm),
            "z_mm": _optional_float(cargo_z_mm),
        }
    else:
        cargo_item = v5_cargo_preset(cargo_mass_g, cargo_position)
        cargo_item["x_mm"] = _optional_float(cargo_x_midship_mm)
        cargo_item["y_mm"] = _optional_float(cargo_y_mm)
        cargo_item["z_mm"] = _optional_float(cargo_z_mm)
    cargo_items.append(cargo_item)

loading_result = loading_v5_weighed(
    base_item,
    cargo_items,
    weighing_basis=weighing_basis,
    electronics={
        "mass_g": electronics["electronics_mass_g"],
        "x_mm": electronics["electronics_x_midship_mm"],
        "y_mm": electronics["electronics_y_mm"],
        "z_mm": electronics["electronics_z_mm"],
    },
)
total_mass_g = loading_result["total_mass_g"]
total_mass_reason = loading_result["unavailable"].get("total_mass_g")

st.subheader("2 · Upright still-water CAD estimate")
if configuration.startswith("V5"):
    st.caption(
        "Nominal V5 geometry: two 200 × 48 × 65 mm pontoons, 120 mm centreline "
        "spacing, and a 65 mm seam reference."
    )
    cad_prediction = v5_upright_draft(total_mass_g, water_density_kg_m3)
    prediction_col1, prediction_col2, prediction_col3 = st.columns(3)
    prediction_col1.metric("Total mass from entered inputs", _display(total_mass_g, 1, " g"))
    prediction_col2.metric("Estimated mean draft", _display(cad_prediction["mean_draft_mm"]))
    prediction_col3.metric(
        "Estimated seam freeboard",
        _display(cad_prediction["seam_freeboard_mm"]),
    )
    if total_mass_reason is not None:
        st.warning(
            f"Total mass and CAD draft/freeboard unavailable — {total_mass_reason}."
        )
    elif cad_prediction["status"] != "ok":
        st.warning(f"CAD estimate unavailable: {cad_prediction['reason']}")
    else:
        st.caption(
            f"{cad_prediction['label']} · source "
            f"{cad_prediction['source']} · revision {cad_prediction['revision']} · "
            f"reference density {cad_prediction['reference_density_kg_m3']:.0f} kg/m³ · "
            f"curve {cad_prediction['table_bounds_mm'][0]:g}–"
            f"{cad_prediction['table_bounds_mm'][1]:g} mm, both pontoons together."
        )
    st.caption(
        "The curve estimates mean draft only. It does not predict waves, local "
        "freeboard at a tilted corner, or measured trim. Estimated freeboard "
        "uses the nominal 65 mm seam reference."
    )
else:
    cad_prediction = {
        "status": "unavailable",
        "reason": "V3 waterplane inputs are unverified; no V3 draft estimate is computed.",
        "mean_draft_mm": None,
        "seam_freeboard_mm": None,
    }
    st.info(cad_prediction["reason"])

cg_cols = st.columns(4)
cg_cols[0].metric(
    "Entered total mass",
    _display(loading_result["total_mass_g"], 1, " g"),
)
cg_cols[1].metric(
    "LCG from midship",
    _display(loading_result["lcg_mm_from_midship"]),
)
cg_cols[2].metric("TCG", _display(loading_result["tcg_mm"]))
cg_cols[3].metric("KG", _display(loading_result["kg_mm"]))
st.caption(
    "LCG origin: midship (0 mm); positive toward the bow. Legacy stern-based "
    "X conversion is applied once at the loading_v5 boundary. Unknown base "
    "centres or cargo Z remain unavailable; Z does not block LCG or TCG."
)
if loading_result["unavailable"]:
    st.caption(
        "Unavailable: "
        + "; ".join(f"{key} — {reason}" for key, reason in loading_result["unavailable"].items())
        + ". Manual draft and trim below do not depend on these mass inputs."
    )

st.subheader("3 · Manual tank readings")
st.caption(
    "Enter the four optional draft readings independently of cargo and sensor "
    "data. Station X defaults are the V5 CAD marks at −75 mm aft and +75 mm forward."
)
station_aft_col, station_fwd_col = st.columns(2)
station_aft_x_mm = station_aft_col.number_input(
    "Aft draft-station X from midship (mm)",
    value=float(V5_DRAFT_STATIONS_MIDSHIP_MM[0]),
    step=1.0,
    key="station_aft_x",
)
station_fwd_x_mm = station_fwd_col.number_input(
    "Forward draft-station X from midship (mm)",
    value=float(V5_DRAFT_STATIONS_MIDSHIP_MM[1]),
    step=1.0,
    key="station_fwd_x",
)
draft_cols = st.columns(4)
aft_port_mm = draft_cols[0].number_input(
    "Aft port draft (mm)", min_value=0.0, value=None, step=0.1, key="aft_port"
)
aft_stbd_mm = draft_cols[1].number_input(
    "Aft starboard draft (mm)", min_value=0.0, value=None, step=0.1, key="aft_stbd"
)
fwd_port_mm = draft_cols[2].number_input(
    "Forward port draft (mm)", min_value=0.0, value=None, step=0.1, key="fwd_port"
)
fwd_stbd_mm = draft_cols[3].number_input(
    "Forward starboard draft (mm)", min_value=0.0, value=None, step=0.1, key="fwd_stbd"
)

if configuration.startswith("V5"):
    seam_reference_choice = st.radio(
        "Seam reference for station-derived freeboard",
        ["Nominal V5 CAD · 65 mm", "Measured seam reference", "Not entered"],
        horizontal=True,
        key="seam_reference_choice",
    )
else:
    seam_reference_choice = st.radio(
        "Seam reference for station-derived freeboard",
        ["Measured seam reference", "Not entered"],
        horizontal=True,
        key="seam_reference_choice_v3",
    )
if seam_reference_choice.startswith("Nominal"):
    seam_reference_mm = V5_SEAM_HEIGHT_MM
    seam_reference_basis = "nominal V5 CAD"
elif seam_reference_choice == "Measured seam reference":
    seam_reference_mm = st.number_input(
        "Measured seam reference from hull bottom (mm)",
        min_value=0.0,
        value=None,
        step=0.1,
        key="measured_seam_reference_mm",
    )
    seam_reference_basis = "measured" if seam_reference_mm is not None else "not entered"
else:
    seam_reference_mm = None
    seam_reference_basis = "not entered"

measured_min_seam_freeboard_mm = st.number_input(
    "Measured minimum seam freeboard around hull (mm)",
    value=None,
    step=0.1,
    key="measured_min_seam_freeboard_mm",
    help="Independent manual measurement; do not substitute a value derived from the four draft stations.",
)
near_level_calm = st.checkbox(
    "This is a near-level, calm-water run suitable for CAD draft comparison",
    value=False,
)
manual_notes = st.text_area("Run notes", value="", key="manual_notes")
sensor_file_reference = st.text_input(
    "Sensor file reference",
    value=f"smarttrim_sensor_{run_id or 'run'}.csv",
    key="sensor_file_reference",
)

tank_summary = tank_reading_summary(
    _optional_float(aft_port_mm),
    _optional_float(aft_stbd_mm),
    _optional_float(fwd_port_mm),
    _optional_float(fwd_stbd_mm),
    seam_height_mm=_optional_float(seam_reference_mm),
)
manual_col1, manual_col2, manual_col3, manual_col4 = st.columns(4)
manual_col1.metric("Mean aft draft", _display(tank_summary["mean_aft_mm"]))
manual_col2.metric("Mean forward draft", _display(tank_summary["mean_forward_mm"]))
manual_col3.metric("Measured trim (aft − forward)", _display(tank_summary["measured_trim_mm"]))
manual_col4.metric(
    "Four-reading mean draft (approx.)",
    _display(tank_summary["mean_draft_approx_mm"]),
)
st.caption(
    "Positive measured trim means the stern is deeper. Transverse draft "
    "difference is starboard mean minus port mean (mm); it is not sensor roll (degrees)."
)
st.metric(
    "Transverse draft difference (starboard − port)",
    _display(tank_summary["transverse_difference_mm"]),
)
derived_freeboard_label = (
    "Derived freeboard at the four marked stations from the nominal V5 CAD "
    "65 mm seam reference"
    if seam_reference_basis == "nominal V5 CAD"
    else f"Derived freeboard at the four marked stations from the {seam_reference_basis} seam reference"
)
st.write(derived_freeboard_label)
st.dataframe(
    pd.DataFrame(
        [
            {"Marked station": name.replace("_", " "), "Derived freeboard (mm)": value}
            for name, value in tank_summary["derived_station_freeboard_mm"].items()
        ]
    ),
    hide_index=True,
    use_container_width=True,
)
st.caption(
    "Station-derived values are not the measured minimum freeboard around the hull; "
    "use the separate manual minimum field for that observation."
)
st.metric(
    "Measured minimum seam freeboard",
    _display(_optional_float(measured_min_seam_freeboard_mm)),
)

if (near_level_calm and configuration.startswith("V5")
        and cad_prediction["status"] == "ok"
        and tank_summary["mean_draft_approx_mm"] is not None):
    prediction_error = draft_prediction_error(
        cad_prediction["mean_draft_mm"],
        tank_summary["mean_draft_approx_mm"],
    )
    error_cols = st.columns(2)
    error_cols[0].metric("Signed measured − CAD error", _display(prediction_error["signed_error_mm"]))
    error_cols[1].metric("Absolute CAD error", _display(prediction_error["abs_error_mm"]))
    st.caption("Comparison uses the four-reading mean approximation for this selected near-level, calm-water run.")
else:
    prediction_error = {"signed_error_mm": None, "abs_error_mm": None}
    st.info(
        "CAD comparison is unavailable unless this is a near-level, calm-water "
        "V5 run with a valid CAD prediction and all four readings. Manual trim remains available."
    )

if st.button("Save manual run record", key="save_manual_run"):
    if not run_id.strip():
        st.error("Enter a run ID before saving the manual record.")
    else:
        record = {
            "run_id": run_id.strip(),
            "cad_version": "V5 SLEEK" if configuration.startswith("V5") else "V3",
            "water_condition": water_condition,
            "water_density_kg_m3": water_density_kg_m3,
            "mooring_setup": mooring_setup,
            "cargo_preset": cargo_case,
            "cargo_position": cargo_label,
            "cargo_mass_g": _optional_float(cargo_mass_g),
            "assembled_base_mass_g": _optional_float(assembled_base_mass_g),
            "base_weighing_basis": weighing_basis,
            **electronics,
            "total_mass_g": total_mass_g,
            "tank_water_depth_m": tank_water_depth_m,
            "cargo_x_midship_mm": _optional_float(cargo_x_midship_mm),
            "cargo_y_mm": _optional_float(cargo_y_mm),
            "cargo_z_mm": _optional_float(cargo_z_mm),
            "coordinate_origin": "midship",
            "draft_station_aft_x_midship_mm": station_aft_x_mm,
            "draft_station_forward_x_midship_mm": station_fwd_x_mm,
            "aft_port_draft_mm": _optional_float(aft_port_mm),
            "aft_starboard_draft_mm": _optional_float(aft_stbd_mm),
            "forward_port_draft_mm": _optional_float(fwd_port_mm),
            "forward_starboard_draft_mm": _optional_float(fwd_stbd_mm),
            **tank_summary,
            "measured_min_seam_freeboard_mm": _optional_float(
                measured_min_seam_freeboard_mm
            ),
            "seam_reference_mm": _optional_float(seam_reference_mm),
            "seam_reference_basis": seam_reference_basis,
            "cad_predicted_mean_draft_mm": cad_prediction["mean_draft_mm"],
            "cad_estimate_status": cad_prediction["status"],
            "near_level_calm_comparison": near_level_calm,
            "signed_draft_error_mm": prediction_error["signed_error_mm"],
            "absolute_draft_error_mm": prediction_error["abs_error_mm"],
            "notes": manual_notes,
            "sensor_file_reference": sensor_file_reference,
        }
        st.session_state.run_records.append(record)
        st.success(f"Saved manual run {record['run_id']}.")

st.subheader("4 · Saved runs and comparisons")
run_records = st.session_state.run_records
if not run_records:
    st.info("No manual run records saved. Enter readings and save; sensor recording is optional.")
else:
    run_frame = pd.DataFrame(run_records)
    st.dataframe(run_frame, hide_index=True, use_container_width=True)
    st.download_button(
        "Download manual run records CSV",
        data=run_frame.to_csv(index=False).encode("utf-8"),
        file_name="smarttrim_manual_runs.csv",
        mime="text/csv",
    )
    if len(run_records) >= 2:
        run_keys = [
            f"{index}: {record['run_id']} · {record['mooring_setup']} · "
            f"{record['cargo_preset']} · {record['cargo_position']}"
            for index, record in enumerate(run_records)
        ]
        left, right = st.columns(2)
        first_key = left.selectbox("Compare run A", run_keys, index=0)
        second_key = right.selectbox("Compare run B", run_keys, index=1)
        first = run_records[int(first_key.split(":", 1)[0])]
        second = run_records[int(second_key.split(":", 1)[0])]
        match = loading_match(first, second)
        match_detail = ""
        if match["differs"]:
            match_detail += " (differs: " + ", ".join(match["differs"]) + ")"
        if match["unknown"]:
            match_detail += " (not documented on both runs: " + ", ".join(match["unknown"]) + ")"
        st.caption(
            f"Documented dry mass and cargo match: {match['status']}{match_detail} · "
            f"Dry boat mass A: {_display(documented_dry_mass_g(first), 1, ' g')} · "
            f"B: {_display(documented_dry_mass_g(second), 1, ' g')} · "
            f"Mooring A: {first['mooring_setup']} · Mooring B: {second['mooring_setup']}"
        )
        st.caption(
            "Checks only the documented dry boat mass (base, plus electronics when "
            "weighed separately) and the cargo case, mass and X/Y/Z. Equal dry mass "
            "does not confirm equal weight distribution: the base and electronics "
            "positions are not compared, so confirm the electronics were not moved "
            "between runs. Missing loading metadata gives \"unknown\", never a match."
        )
        if match["status"] == "yes" and first["mooring_setup"] != second["mooring_setup"]:
            st.info(
                "Documented dry mass and cargo match, so these runs can compare the two "
                "slack mooring setups if the electronics and base were not moved between runs."
            )
        comparison = pd.DataFrame(
            [
                {"Run": "A", "Measured trim (mm)": first["measured_trim_mm"],
                 "Mean draft approx. (mm)": first["mean_draft_approx_mm"],
                 "Measured minimum seam freeboard (mm)": first["measured_min_seam_freeboard_mm"]},
                {"Run": "B", "Measured trim (mm)": second["measured_trim_mm"],
                 "Mean draft approx. (mm)": second["mean_draft_approx_mm"],
                 "Measured minimum seam freeboard (mm)": second["measured_min_seam_freeboard_mm"]},
            ]
        )
        st.dataframe(comparison, hide_index=True, use_container_width=True)

st.subheader("5 · Under-keel clearance alert")
water_depth_m = st.number_input(
    "Water depth (m), optional",
    min_value=0.0,
    value=None,
    step=0.01,
    key="water_depth_m",
)
if water_depth_m is None:
    st.warning(
        "Depth unavailable — under-keel clearance cannot be assessed. "
        "Draft and seam freeboard are not substitutes for water depth."
    )
    missing_depth_alert = {
        "alert_id": "CLEARANCE_UNASSESSED",
        "route_leg": "Tank test / selected water",
        "facts": [
            {
                "id": "F_DEPTH_MISSING",
                "label": "Water depth",
                "value": None,
                "unit": "m",
                "provenance": "not entered",
            }
        ],
        "missing_inputs": ["water depth"],
    }
    if st.button("Explain missing-depth alert", key="explain_depth_alert"):
        st.session_state.depth_explanation = explain_alert(missing_depth_alert)
    if st.session_state.get("depth_explanation"):
        explanation = st.session_state.depth_explanation
        st.caption(f"Source: {explanation['source']}")
        st.write(explanation["text"])
else:
    st.info(
        f"Entered water depth: {water_depth_m:.2f} m. Under-keel clearance "
        "remains uncomputed; water-level corrections and a verified depth source are required."
    )

st.subheader("6 · Sensor modes")
st.caption(
    "Arduino sketch protocol: 115200 baud; CSV columns "
    "`timestamp_ms,roll_deg,pitch_deg`; timestamp unit is Arduino `millis()` (ms). "
    "Roll and pitch are motion angles, not measured draft or trim."
)
sensor_mode = st.radio(
    "Sensor data source",
    ["Simulated", "Recorded CSV", "Live Arduino"],
    horizontal=True,
    key="sensor_mode",
)

axis_convention = (
    "Sketch default assumption: X forward, Y lateral, Z up; signs pending physical bench check"
)
sensor_metadata = _run_sensor_metadata(
    run_id=run_id.strip(),
    configuration="V5 SLEEK" if configuration.startswith("V5") else "V3",
    water_condition=water_condition,
    mooring_setup=mooring_setup,
    cargo_preset=cargo_case,
    cargo_mass_g=_optional_float(cargo_mass_g),
    base_mass_g=_optional_float(assembled_base_mass_g),
    cargo_x_mm=_optional_float(cargo_x_midship_mm),
    cargo_y_mm=_optional_float(cargo_y_mm),
    cargo_z_mm=_optional_float(cargo_z_mm),
    axis_convention=axis_convention,
    notes=manual_notes,
    sensor_file_reference=sensor_file_reference,
    weighing_basis=weighing_basis,
    electronics=electronics,
    tank_water_depth_m=tank_water_depth_m,
)


def _show_motion_recording(frame, source_label):
    if frame is None or frame.empty:
        st.info("Recording unavailable — no valid sensor or CSV samples.")
        return
    stats = motion_stats(frame)
    left, right = st.columns(2)
    roll_stats = stats["roll_deg"]
    pitch_stats = stats["pitch_deg"]
    left.metric("Max |roll| per selected recording", _display(roll_stats["max_abs"], 2, "°"))
    right.metric("Max |pitch| per selected recording", _display(pitch_stats["max_abs"], 2, "°"))
    st.caption(
        f"{source_label} · signed roll min/max "
        f"{_display(roll_stats['min'], 2, '°')} / {_display(roll_stats['max'], 2, '°')} · "
        f"signed pitch min/max {_display(pitch_stats['min'], 2, '°')} / "
        f"{_display(pitch_stats['max'], 2, '°')} · {stats['samples']} samples."
    )
    chart = frame.set_index("time_s")[["roll_deg", "pitch_deg"]]
    st.line_chart(chart)


if sensor_mode == "Simulated":
    st.info("SIMULATED DATA — synthetic motion only; never measured.")
    sim_left, sim_right = st.columns(2)
    simulated_roll_amplitude = sim_left.slider(
        "Simulated roll amplitude (degrees)", min_value=0.0, max_value=20.0,
        value=4.0, step=0.5,
    )
    simulated_pitch_offset = sim_right.slider(
        "Simulated pitch offset (degrees)", min_value=-15.0, max_value=15.0,
        value=1.0, step=0.5,
    )
    simulated_frame = build_export_frame(
        simulated_rows(simulated_roll_amplitude, simulated_pitch_offset),
        {**sensor_metadata, "source": "simulated"},
    )
    _show_motion_recording(simulated_frame, "Simulated (not measured)")
    st.download_button(
        "Download simulated sensor CSV",
        data=export_csv_bytes(simulated_frame),
        file_name=f"smarttrim_simulated_{run_id or 'run'}.csv",
        mime="text/csv",
    )
elif sensor_mode == "Recorded CSV":
    uploaded_recording = st.file_uploader(
        "Upload a SmartTrim sensor CSV", type=["csv"], key="recorded_csv_upload"
    )
    if uploaded_recording is None:
        st.info("Recording unavailable — upload a CSV. Manual tank records remain usable.")
    else:
        recording, problems = load_recording(uploaded_recording.getvalue())
        if problems:
            st.error("Could not load recording: " + "; ".join(problems))
        elif recording is None:
            st.error("Could not load recording: no valid sensor samples.")
        else:
            recording["recording_key"] = (
                recording["run_id"].astype(str)
                + " · "
                + recording["source"].astype(str)
                + " · "
                + recording["cad_version"].fillna("CAD unknown").astype(str)
            )
            recording_keys = recording["recording_key"].drop_duplicates().tolist()
            selected_key = st.selectbox("Selected recording", recording_keys)
            selected_recording = (
                recording.loc[recording["recording_key"] == selected_key]
                .sort_values("time_s")
                .copy()
            )
            source_value = str(selected_recording["source"].iloc[0])
            if is_measured(source_value):
                source_label = "Recorded sensor measurements"
            elif source_value == "simulated":
                source_label = "Recorded simulated data (not measured)"
            else:
                source_label = f"Recorded source: {source_value}"
            # Show the recording's own notes (e.g. a bench-test statement) above
            # its summary; recordings without notes show nothing extra.
            recording_notes = (
                selected_recording["notes"].dropna().astype(str).str.strip()
            )
            recording_notes = recording_notes[recording_notes != ""].unique()
            if len(recording_notes):
                st.info("Recording notes: " + " · ".join(recording_notes))
            _show_motion_recording(selected_recording, source_label)
            first_row = selected_recording.iloc[0]
            st.caption(
                "Run metadata: "
                f"mooring={first_row['mooring_setup']}; "
                f"cargo case={first_row['cargo_preset']}; "
                f"cargo load={format_grams(first_row['load_g'])}; "
                + describe_weighing(
                    first_row["base_weighing_basis"],
                    first_row["base_mass_g"],
                    first_row["electronics_mass_g"],
                )
                + "; "
                + describe_cargo_position(
                    first_row["cargo_preset"],
                    first_row["cargo_x_midship_mm"],
                    first_row["cargo_y_mm"],
                    first_row["cargo_z_mm"],
                )
                + f"; Tank water depth: {format_measure(first_row['tank_water_depth_m'], 'm')}."
            )
            st.dataframe(selected_recording, hide_index=True, use_container_width=True)
elif sensor_mode == "Live Arduino":
    st.caption(
        "Hardware-specific pin voltage and sensor axis mapping are intentionally "
        "not changed here; validate the actual board and its documentation first."
    )
    st.markdown(
        "**Bench checklist:** photograph the actual board and X/Y/Z markings; "
        "mark BOW, PORT and STARBOARD; secure the sensor flat; record several "
        "seconds of flat readings; tilt bow-up/down and port/starboard independently; "
        "record the observed axis mapping and signs; recalibrate after any mounting "
        "orientation change; check and record USB cable slack."
    )
    connection = st.session_state.live_connection
    if connection is not None and not is_arduino_connected(connection):
        safe_disconnect(connection)
        st.session_state.live_connection = None
        st.session_state.live_recording = False
        connection = None

    if is_arduino_connected(connection):
        st.success("Arduino serial port connected.")
        if st.button("Disconnect Arduino"):
            safe_disconnect(connection)
            st.session_state.live_connection = None
            st.session_state.live_recording = False
            st.rerun()
    else:
        ports = available_ports()
        if not ports:
            st.info("No serial port connected. Manual and offline modes remain available.")
        else:
            selected_port = st.selectbox("Serial port", [port[0] for port in ports])
            st.caption(
                "Connecting normally resets a Nano, and the sketch then stores its "
                "current pose as 0°/0° (about 3 s). Secure the sensor flat and still "
                "before connecting."
            )
            if st.button("Connect Arduino"):
                try:
                    st.session_state.live_connection = connect_arduino(selected_port)
                    st.session_state.live_rows = []
                    st.session_state.live_latest = None
                    st.session_state.live_status = None
                    st.rerun()
                except (OSError, ValueError, serial.SerialException) as exc:
                    st.error(f"Could not connect to Arduino: {exc}")

    if st.session_state.live_recording:
        if st.button("Stop sensor recording"):
            st.session_state.live_recording = False
            st.rerun()
    elif st.button(
        "Start sensor recording",
        disabled=not is_arduino_connected(st.session_state.live_connection),
    ):
        st.session_state.live_rows = []
        st.session_state.live_recording = True
        st.rerun()

    @st.fragment(run_every=0.5)
    def live_sensor_monitor():
        live_connection = st.session_state.live_connection
        if not is_arduino_connected(live_connection):
            st.info("Live sensor unavailable — connect the actual board to record.")
            return
        try:
            for _ in range(50):
                if live_connection.in_waiting <= 0:
                    break
                measurement, status = read_line(live_connection)
                if status is not None:
                    st.session_state.live_status = status
                if measurement is None:
                    continue
                measurement["recorded_at_utc"] = datetime.now(timezone.utc).isoformat()
                st.session_state.live_latest = measurement
                if st.session_state.live_recording:
                    st.session_state.live_rows.append(dict(measurement))
        except (OSError, ValueError, serial.SerialException) as exc:
            st.error(f"Sensor read failed: {exc}")
            st.session_state.live_recording = False
            return

        live_status = st.session_state.live_status
        if live_status is not None:
            if live_status.startswith(("WARN", "ERROR")):
                st.warning(f"Sketch status: {live_status}")
            else:
                st.caption(f"Sketch status: {live_status}")

        latest = st.session_state.live_latest
        if latest is not None:
            left, right = st.columns(2)
            left.metric("Live roll", f"{latest['roll_deg']:+.2f}°")
            right.metric("Live pitch", f"{latest['pitch_deg']:+.2f}°")
        else:
            st.info("Waiting for valid sensor samples.")

        live_frame = build_export_frame(
            st.session_state.live_rows,
            {**sensor_metadata, "source": "arduino_mpu6050"},
        )
        _show_motion_recording(live_frame, "Live Arduino sensor measurements")
        if not live_frame.empty:
            st.download_button(
                "Download Live sensor CSV",
                data=export_csv_bytes(live_frame),
                file_name=f"smarttrim_sensor_{run_id or 'run'}.csv",
                mime="text/csv",
            )

    live_sensor_monitor()

st.divider()
st.caption(
    "Progressive tests: base only, then centre 150/250/350/400 g as Olga permits "
    "after measured freeboard and leak checks. Save each run with the same "
    "run ID as its sensor CSV. No tank, sensor, or watertight validation is claimed."
)
