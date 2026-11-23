import math

import pytest

from calculations import (displacement_and_draft, loading_cg, loading_v2,
                          measured_trim_mm, draft_freeboard_v2,
                          CONSTANT_AREA_DRAFT_BASIS, draft_seam_freeboard_v2,
                          V2_NOMINAL_CAD_GEOMETRY, V2_SEAM_DRAFT_BASIS,
                          V5_CAPACITY_SOURCE, V5_CORE_PRINT_MASS_G)
import calculations

def test_displacement():
    result = displacement_and_draft(180, [{"mass_g": 400, "y_mm": 0}], 1000)
    assert abs(result["displaced_l"] - 0.58) < 1e-9
    assert 0 < result["draft_mm"] < 52

def test_symmetric_load():
    assert loading_cg(180, [{"mass_g": 150, "y_mm": 0}])["heel_deg"] == 0

def test_offset_load():
    assert loading_cg(180, [{"mass_g": 150, "y_mm": 40}])["heel_deg"] > 0

def test_draft_matches_catamaran_geometry():
    cargo = [{"mass_g": 400, "y_mm": 0}]
    result = displacement_and_draft(180, cargo, 1000)
    assert abs(result["draft_mm"] - 33.2264) < 0.01 


# --- V2 loading model -------------------------------------------------------
# ILLUSTRATIVE INPUTS ONLY. Structure mass 188.6 g is the CAD estimate; its
# X = 95 mm, Y = 0 mm and Z = 30 mm are made-up test values, NOT measurements.
# Demo loads are placed at (100, y, 80) mm as specified for the V2 demo.
ILLUSTRATIVE_STRUCTURE = {"name": "structure", "mass_g": 188.6,
                          "x_mm": 95.0, "y_mm": 0.0, "z_mm": 30.0}

# mass_g -> (total_g, LCG_mm, {Y_mm: TCG_mm}, KG_mm), worked by hand:
# LCG = (188.6*95 + m*100)/(188.6+m); TCG = m*Y/(188.6+m);
# KG = (188.6*30 + m*80)/(188.6+m)
DEMO_EXPECTED = {
    150: (338.6, 97.215003, {-20: -8.860012, 0: 0.0, 20: 8.860012}, 52.150030),
    250: (438.6, 97.849977, {-20: -11.399909, 0: 0.0, 20: 11.399909}, 58.499772),
    400: (588.6, 98.397893, {-20: -13.591573, 0: 0.0, 20: 13.591573}, 63.978933),
}


@pytest.mark.parametrize("mass_g", [150, 250, 400])
@pytest.mark.parametrize("y_mm", [-20, 0, 20])
def test_v2_demo_loads_illustrative(mass_g, y_mm):
    load = {"name": f"demo {mass_g} g", "mass_g": mass_g,
            "x_mm": 100, "y_mm": y_mm, "z_mm": 80}
    r = loading_v2(ILLUSTRATIVE_STRUCTURE, [load])
    total, lcg, tcg_by_y, kg = DEMO_EXPECTED[mass_g]
    assert abs(r["total_mass_g"] - total) < 1e-9
    assert abs(r["lcg_mm"] - lcg) < 1e-5
    assert abs(r["tcg_mm"] - tcg_by_y[y_mm]) < 1e-5
    assert abs(r["kg_mm"] - kg) < 1e-5
    assert r["all_outputs_available"] and r["missing"] == []


def test_v2_moving_motor_aft_decreases_lcg():
    motor = {"name": "motor", "mass_g": 50, "y_mm": 0, "z_mm": 45}
    fwd = loading_v2(ILLUSTRATIVE_STRUCTURE, [{**motor, "x_mm": 35}])
    aft = loading_v2(ILLUSTRATIVE_STRUCTURE, [{**motor, "x_mm": 20}])
    assert aft["lcg_mm"] < fwd["lcg_mm"]
    assert aft["total_mass_g"] == fwd["total_mass_g"]


def test_v2_x_zero_is_a_valid_coordinate():
    r = loading_v2({"mass_g": 100, "x_mm": 0, "y_mm": 0, "z_mm": 0},
                   [{"mass_g": 100, "x_mm": 200, "y_mm": 0, "z_mm": 0}])
    assert r["lcg_mm"] == 100
    assert r["kg_mm"] == 0 and r["missing"] == []


def test_v2_unknown_mass_blocks_total_and_all_centres():
    motor = {"name": "motor", "mass_g": None, "x_mm": 35, "y_mm": 0, "z_mm": 45}
    r = loading_v2(ILLUSTRATIVE_STRUCTURE, [motor])
    assert r["total_mass_g"] is None
    assert r["lcg_mm"] is None and r["tcg_mm"] is None and r["kg_mm"] is None
    assert r["missing"] == ["motor.mass_g"]
    assert not r["all_outputs_available"]
    assert "motor" in r["included"]


def test_v2_missing_x_affects_only_lcg():
    s = {**ILLUSTRATIVE_STRUCTURE, "x_mm": None}
    r = loading_v2(s, [{"mass_g": 150, "x_mm": 100, "y_mm": 20, "z_mm": 80}])
    assert r["lcg_mm"] is None
    assert abs(r["tcg_mm"] - 8.860012) < 1e-5
    assert abs(r["kg_mm"] - 52.150030) < 1e-5
    assert r["missing"] == ["structure.x_mm"]
    assert set(r["unavailable"]) == {"lcg_mm"}


def test_v2_missing_z_affects_only_kg():
    s = {**ILLUSTRATIVE_STRUCTURE, "z_mm": None}
    r = loading_v2(s, [{"mass_g": 150, "x_mm": 100, "y_mm": 20, "z_mm": 80}])
    assert r["kg_mm"] is None
    assert abs(r["lcg_mm"] - 97.215003) < 1e-5
    assert abs(r["tcg_mm"] - 8.860012) < 1e-5
    assert set(r["unavailable"]) == {"kg_mm"}


def test_v2_structure_with_unknown_x_and_z_as_in_v2_spec():
    # Spec state: CAD mass, X and Z unknown, Y = 0 as a labelled assumption.
    s = {"name": "structure", "mass_g": 188.6, "x_mm": None, "y_mm": 0, "z_mm": None}
    r = loading_v2(s)
    assert r["total_mass_g"] == 188.6 and r["tcg_mm"] == 0
    assert r["lcg_mm"] is None and r["kg_mm"] is None
    assert r["missing"] == ["structure.x_mm", "structure.z_mm"]


def test_v2_zero_mass_item_coordinates_do_not_block():
    r = loading_v2(ILLUSTRATIVE_STRUCTURE,
                   [{"name": "empty slot", "mass_g": 0, "x_mm": None,
                     "y_mm": None, "z_mm": None}])
    assert r["lcg_mm"] == 95 and r["all_outputs_available"]
    assert "empty slot.x_mm" in r["missing"]


def test_v2_excluded_item_is_listed_not_used():
    battery = {"name": "battery 1", "mass_g": None, "x_mm": 100,
               "y_mm": -18, "z_mm": 82, "included": False}
    r = loading_v2(ILLUSTRATIVE_STRUCTURE, [battery])
    assert r["excluded"] == ["battery 1"] and r["total_mass_g"] == 188.6


def test_v2_nan_is_unknown_not_zero():
    r = loading_v2({**ILLUSTRATIVE_STRUCTURE, "mass_g": math.nan})
    assert r["total_mass_g"] is None and r["missing"] == ["structure.mass_g"]


def test_v2_rejects_absent_field_and_negative_mass():
    with pytest.raises(ValueError):
        loading_v2({"mass_g": 10, "x_mm": 0, "y_mm": 0})
    with pytest.raises(ValueError):
        loading_v2({**ILLUSTRATIVE_STRUCTURE, "mass_g": -1})


# --- Measured trim (aft draft minus forward draft) ---------------------------
def test_measured_trim_stern_deeper_is_positive():
    assert measured_trim_mm(30.0, 25.5) == 4.5


def test_measured_trim_bow_deeper_is_negative():
    assert measured_trim_mm(25.0, 31.0) == -6.0


def test_measured_trim_equal_drafts_is_zero():
    assert measured_trim_mm(28.0, 28.0) == 0


def test_measured_trim_zero_reading_is_valid():
    assert measured_trim_mm(0, 3.0) == -3.0
    assert measured_trim_mm(4.0, 0) == 4.0


def test_measured_trim_missing_reading_returns_none():
    assert measured_trim_mm(None, 25.0) is None
    assert measured_trim_mm(30.0, None) is None
    assert measured_trim_mm(math.nan, 25.0) is None


def test_measured_trim_rejects_negative_reading():
    with pytest.raises(ValueError):
        measured_trim_mm(-1.0, 25.0)


# --- V2 mean draft and freeboard ---------------------------------------------
# ILLUSTRATIVE GEOMETRY ONLY, not confirmed by Olga: 9600 mm^2 is a plain
# 200 x 48 mm rectangle, 65 mm is the stated V2 pontoon height, 2 hulls,
# fresh water 1000 kg/m^3. Expected draft = m * 1e6 / (rho * 2 * 9600).
ILLUSTRATIVE_V2 = dict(waterplane_area_per_hull_mm2=9600, hull_count=2,
                       freeboard_reference_height_mm=65, density_kg_m3=1000)


def test_v2_draft_and_freeboard_illustrative():
    r = draft_freeboard_v2(total_mass_g=588.6, **ILLUSTRATIVE_V2)
    assert abs(r["mean_draft_mm"] - 30.65625) < 1e-9
    assert abs(r["freeboard_mm"] - 34.34375) < 1e-9
    assert r["draft_reaches_reference_height"] is False
    assert r["draft_basis"] == CONSTANT_AREA_DRAFT_BASIS
    assert "constant-area estimate" in r["draft_basis"]
    assert r["all_outputs_available"] and r["missing"] == []


def test_v2_missing_height_keeps_draft():
    r = draft_freeboard_v2(total_mass_g=338.6,
                           **{**ILLUSTRATIVE_V2, "freeboard_reference_height_mm": None})
    assert abs(r["mean_draft_mm"] - 17.6354166667) < 1e-9
    assert r["draft_basis"] == CONSTANT_AREA_DRAFT_BASIS
    assert r["freeboard_mm"] is None
    assert r["draft_reaches_reference_height"] is None
    assert r["missing"] == ["freeboard_reference_height_mm"]
    assert set(r["unavailable"]) == {"freeboard_mm"}


def test_v2_missing_area_blocks_draft_and_freeboard():
    r = draft_freeboard_v2(total_mass_g=588.6,
                           **{**ILLUSTRATIVE_V2, "waterplane_area_per_hull_mm2": None})
    assert r["mean_draft_mm"] is None and r["freeboard_mm"] is None
    assert r["draft_basis"] is None
    assert r["missing"] == ["waterplane_area_per_hull_mm2"]
    assert set(r["unavailable"]) == {"mean_draft_mm", "freeboard_mm"}


def test_v2_unknown_mass_from_loading_v2_blocks_draft():
    total = loading_v2({"mass_g": None, "x_mm": None, "y_mm": 0,
                        "z_mm": None})["total_mass_g"]
    r = draft_freeboard_v2(total_mass_g=total, **ILLUSTRATIVE_V2)
    assert r["mean_draft_mm"] is None and r["freeboard_mm"] is None
    assert r["missing"] == ["total_mass_g"]


def test_v2_nan_geometry_is_unknown():
    r = draft_freeboard_v2(total_mass_g=588.6,
                           **{**ILLUSTRATIVE_V2, "hull_count": math.nan})
    assert r["mean_draft_mm"] is None and r["missing"] == ["hull_count"]


def test_v2_denser_water_gives_smaller_draft():
    fresh = draft_freeboard_v2(total_mass_g=588.6, **ILLUSTRATIVE_V2)
    sea = draft_freeboard_v2(total_mass_g=588.6,
                             **{**ILLUSTRATIVE_V2, "density_kg_m3": 1025})
    assert abs(sea["mean_draft_mm"] - 29.9085365854) < 1e-9
    assert sea["mean_draft_mm"] < fresh["mean_draft_mm"]


def test_v2_flags_draft_at_reference_height():
    # 1248 g * 1e6 / (1000 * 19200) = 65 mm exactly
    r = draft_freeboard_v2(total_mass_g=1248, **ILLUSTRATIVE_V2)
    assert r["freeboard_mm"] == 0 and r["draft_reaches_reference_height"] is True


def test_v2_matches_v1_when_given_v1_geometry():
    # V1 values passed explicitly; the V1 function itself is unchanged.
    v1 = displacement_and_draft(180, [{"mass_g": 400, "y_mm": 0}], 1000)
    v2 = draft_freeboard_v2(total_mass_g=580, waterplane_area_per_hull_mm2=8728,
                            hull_count=2, freeboard_reference_height_mm=52,
                            density_kg_m3=1000)
    assert abs(v2["mean_draft_mm"] - v1["draft_mm"]) < 1e-9
    assert abs(v2["freeboard_mm"] - v1["freeboard_mm"]) < 1e-9


def test_v2_draft_rejects_invalid_inputs():
    for bad in ({"waterplane_area_per_hull_mm2": 0}, {"hull_count": 1.5},
                {"density_kg_m3": -1000}, {"freeboard_reference_height_mm": "65"}):
        with pytest.raises(ValueError):
            draft_freeboard_v2(total_mass_g=588.6, **{**ILLUSTRATIVE_V2, **bad})
    with pytest.raises(ValueError):
        draft_freeboard_v2(total_mass_g=-1, **ILLUSTRATIVE_V2)
    with pytest.raises(TypeError):  # keyword-only, all required
        draft_freeboard_v2(588.6, 9600, 2, 65, 1000)


# --- V2 seam freeboard (Olga's nominal CAD geometry) --------------------------
# Geometry: nominal CAD values confirmed by Olga (0.008728 m^2 per pontoon,
# 2 pontoons, 65 mm seam). The 500 g / 1000 kg/m^3 load is ILLUSTRATIVE ONLY.
# Expected: 0.0005 m^3 / (2 * 0.008728 m^2) = 28.6434 mm; 65 - 28.6434 = 36.3566 mm.
CAD = dict(waterplane_area_per_pontoon_m2=0.008728, pontoon_count=2,
           seam_height_mm=65.0)


def seam(mass_g, **overrides):
    args = {"total_mass_g": mass_g, "density_kg_m3": 1000, **CAD, **overrides}
    return draft_seam_freeboard_v2(**args)


def test_seam_illustrative_500g_with_cad_geometry():
    r = seam(500)
    assert abs(r["displaced_volume_m3"] - 0.0005) < 1e-15
    assert abs(r["mean_draft_mm"] - 28.64) < 0.01
    assert abs(r["mean_draft_mm"] - 28.643446) < 1e-5
    assert abs(r["seam_freeboard_mm"] - 36.36) < 0.01
    assert r["draft_basis"] == V2_SEAM_DRAFT_BASIS
    assert r["within_constant_area_range"] is True
    assert r["reaches_or_exceeds_seam"] is False
    assert r["seam_status"] == "below nominal seam (upright model)"
    assert r["flags"] == [] and r["all_outputs_available"] and r["missing"] == []


def test_seam_handoff_constants_match_olga_cad_values():
    assert V2_NOMINAL_CAD_GEOMETRY == CAD


def test_seam_pontoon_count_applied_once():
    one = seam(500, pontoon_count=1)
    two = seam(500)
    assert abs(one["mean_draft_mm"] - 2 * two["mean_draft_mm"]) < 1e-9


def test_seam_missing_height_keeps_draft():
    r = seam(500, seam_height_mm=None)
    assert abs(r["mean_draft_mm"] - 28.643446) < 1e-5
    assert r["seam_freeboard_mm"] is None and r["seam_status"] is None
    assert r["reaches_or_exceeds_seam"] is None
    assert r["missing"] == ["seam_height_mm"]
    assert set(r["unavailable"]) == {"seam_freeboard_mm", "seam_status"}


def test_seam_missing_geometry_keeps_displaced_volume():
    r = seam(500, waterplane_area_per_pontoon_m2=None, pontoon_count=None)
    assert abs(r["displaced_volume_m3"] - 0.0005) < 1e-15
    assert r["mean_draft_mm"] is None and r["seam_freeboard_mm"] is None
    assert r["within_constant_area_range"] is None and r["draft_basis"] is None
    assert r["missing"] == ["waterplane_area_per_pontoon_m2", "pontoon_count"]
    assert set(r["unavailable"]) == {"mean_draft_mm", "within_constant_area_range",
                                     "seam_freeboard_mm", "seam_status"}


def test_seam_missing_mass_or_density_blocks_everything():
    for r in (seam(None), seam(500, density_kg_m3=math.nan)):
        assert r["displaced_volume_m3"] is None and r["mean_draft_mm"] is None
        assert r["seam_freeboard_mm"] is None and not r["all_outputs_available"]
        assert "displaced_volume_m3" in r["unavailable"]


def test_seam_boundary_reaches_and_exceeds():
    draft = seam(500)["mean_draft_mm"]
    at = seam(500, seam_height_mm=draft)
    assert at["seam_freeboard_mm"] == 0 and at["reaches_or_exceeds_seam"] is True
    assert at["seam_status"] == "reaches nominal seam (upright model)"
    assert at["seam_status"] in at["flags"]
    over = seam(500, seam_height_mm=draft - 0.01)
    assert over["seam_freeboard_mm"] < 0
    assert over["seam_status"] == "exceeds nominal seam (upright model)"
    under = seam(500, seam_height_mm=draft + 0.01)
    assert under["reaches_or_exceeds_seam"] is False and under["flags"] == []


def test_seam_flags_drafts_outside_constant_area_range():
    shallow = seam(40)          # 40 g -> about 2.29 mm, below 2.4 mm
    assert shallow["mean_draft_mm"] < 2.4
    assert shallow["within_constant_area_range"] is False
    assert any("below 2.4 mm" in f for f in shallow["flags"])
    edge = seam(41.8944)        # 2.4 mm boundary is inside the range
    assert abs(edge["mean_draft_mm"] - 2.4) < 1e-9
    deep = seam(1200)           # 1200 g -> about 68.7 mm, beyond range and seam
    assert deep["within_constant_area_range"] is False
    assert any("above 65.0 mm" in f for f in deep["flags"])
    assert deep["seam_status"] == "exceeds nominal seam (upright model)"


def test_seam_draft_is_not_offset_by_range_floor():
    # 2.4 mm is a range boundary only: draft is volume / area, no added offset.
    r = seam(500)
    assert abs(r["mean_draft_mm"] - 0.0005 / (2 * 0.008728) * 1000) < 1e-12


def test_seam_compatible_with_v1_and_v1_constants_unchanged():
    assert calculations.HULL_WATERPLANE_AREA_M2 == 0.008728
    assert calculations.HULL_COUNT == 2 and calculations.MAX_HEIGHT_M == 0.052
    v1 = displacement_and_draft(180, [{"mass_g": 400, "y_mm": 0}], 1000)
    v2 = seam(580)
    assert abs(v2["mean_draft_mm"] - v1["draft_mm"]) < 1e-9
    assert abs(v2["displaced_volume_m3"] * 1000 - v1["displaced_l"]) < 1e-12
    # V1 freeboard uses the 52 mm V1 height; V2 uses the 65 mm seam.
    assert abs(v2["seam_freeboard_mm"] - v1["freeboard_mm"] - 13) < 1e-9


def test_seam_rejects_invalid_inputs():
    for bad in ({"pontoon_count": 1.5}, {"waterplane_area_per_pontoon_m2": 0},
                {"density_kg_m3": -1}, {"seam_height_mm": "65"}):
        with pytest.raises(ValueError):
            seam(500, **bad)
    with pytest.raises(ValueError):
        seam(-1)
    with pytest.raises(TypeError):  # keyword-only, all required
        draft_seam_freeboard_v2(500, 1000, 0.008728, 2, 65)


# --- V5: coordinates, presets, CAD curve, tank readings -------------------------
# ILLUSTRATIVE masses only (300 g base, presets). The curve values are the V5 CAD
# table itself, not measurements.
from calculations import (midship_to_stern_x, stern_to_midship_x, v5_cargo_preset,
                          loading_v5, v5_upright_draft, tank_reading_summary,
                          draft_prediction_error, V5_CAPACITY_TABLE,
                          V5_CARGO_PRESETS_G, V5_ESTIMATE_LABEL)

ILLUSTRATIVE_BASE_V5 = {"name": "base", "mass_g": 300.0, "x_mm": 0.0, "y_mm": 0.0, "z_mm": 40.0}


def test_v5_coordinate_conversion_centre_and_aft():
    assert midship_to_stern_x(0) == 100.0      # centre
    assert midship_to_stern_x(-20) == 80.0     # aft preset
    assert midship_to_stern_x(-100) == 0.0 and midship_to_stern_x(100) == 200.0
    assert stern_to_midship_x(80) == -20.0
    assert midship_to_stern_x(None) is None and midship_to_stern_x(math.nan) is None


def test_v5_loading_converts_once_and_labels_both_origins():
    r = loading_v5(ILLUSTRATIVE_BASE_V5, [v5_cargo_preset(150, "aft")])
    expected_stern = (300 * 100 + 150 * 80) / 450          # 93.333 mm from stern
    assert abs(r["lcg_mm_from_stern"] - expected_stern) < 1e-9
    assert abs(r["lcg_mm_from_midship"] - (expected_stern - 100)) < 1e-9
    assert "midship" in r["input_x_origin"]
    assert "lcg_mm" not in r
    assert ILLUSTRATIVE_BASE_V5["x_mm"] == 0.0             # caller's dict unchanged


def test_v5_presets_are_separate_and_never_summed():
    assert V5_CARGO_PRESETS_G == (150.0, 250.0, 350.0, 400.0)
    for mass in V5_CARGO_PRESETS_G:
        r = loading_v5(ILLUSTRATIVE_BASE_V5, [v5_cargo_preset(mass, "centre")])
        assert r["total_mass_g"] == 300.0 + mass          # one block at a time
    stbd = v5_cargo_preset(250, "starboard")
    assert (stbd["x_mm"], stbd["y_mm"], stbd["z_mm"]) == (0.0, 20.0, None)
    aft = v5_cargo_preset(350, "aft")
    assert (aft["x_mm"], aft["y_mm"]) == (-20.0, 0.0)
    unknown = v5_cargo_preset(None, "centre")
    assert unknown["mass_g"] is None and (unknown["x_mm"], unknown["y_mm"]) == (0.0, 0.0)


def test_v5_unknown_z_does_not_block_lcg_or_tcg_and_zero_is_kept():
    r = loading_v5(ILLUSTRATIVE_BASE_V5, [v5_cargo_preset(150, "starboard")])
    assert r["kg_mm"] is None                               # preset Z unknown
    assert r["lcg_mm_from_midship"] == 0.0                  # genuine zero kept
    assert abs(r["tcg_mm"] - 150 * 20 / 450) < 1e-9
    blank_base = {**ILLUSTRATIVE_BASE_V5, "mass_g": None}
    r2 = loading_v5(blank_base, [v5_cargo_preset(150, "centre")])
    assert r2["total_mass_g"] is None and r2["lcg_mm_from_stern"] is None


@pytest.mark.parametrize("draft_mm, grams", V5_CAPACITY_TABLE)
def test_v5_curve_reproduces_exact_table_points(draft_mm, grams):
    r = v5_upright_draft(grams, 1000)
    assert r["status"] == "ok" and abs(r["mean_draft_mm"] - draft_mm) < 1e-9
    assert abs(r["seam_freeboard_mm"] - (65 - draft_mm)) < 1e-9


def test_v5_curve_interpolates_and_matches_cad_readme():
    r = v5_upright_draft(458.1, 1000)                       # README: 33.6 mm, 31.4 mm
    assert abs(r["mean_draft_mm"] - (30 + 5 * (458.1 - 404.11) / (478.19 - 404.11))) < 1e-9
    assert round(r["mean_draft_mm"], 1) == 33.6 and round(r["seam_freeboard_mm"], 1) == 31.4
    assert r["label"] == V5_ESTIMATE_LABEL
    assert r["covers"] == "both pontoons together" and "V5" in r["revision"]
    assert r["reference_density_kg_m3"] == 1000
    assert r["table_bounds_mm"] == (0.0, 65.0)
    assert r["table_bounds_displacement_g"] == (0.0, 918.81)
    assert V5_CORE_PRINT_MASS_G == 308.1
    assert V5_CAPACITY_SOURCE["source"].endswith("capacity_still_water")
    assert "20–21 November 2026" in V5_CAPACITY_SOURCE["revision"]


def test_v5_curve_density_uses_volume_conservation_not_double_counting():
    sea = v5_upright_draft(512.5, 1025)          # same volume as 500 g of freshwater
    fresh = v5_upright_draft(500.0, 1000)
    assert abs(sea["equivalent_freshwater_g"] - 500.0) < 1e-9
    assert abs(sea["mean_draft_mm"] - fresh["mean_draft_mm"]) < 1e-9
    assert v5_upright_draft(500, 1025)["mean_draft_mm"] < fresh["mean_draft_mm"]


def test_v5_curve_missing_and_out_of_range_are_explicit():
    assert v5_upright_draft(None)["status"] == "unavailable"
    assert v5_upright_draft(500, None)["status"] == "unavailable"
    over = v5_upright_draft(918.82, 1000)
    assert over["status"] == "out_of_range" and over["mean_draft_mm"] is None
    assert "Not extrapolated" in over["reason"]
    assert v5_upright_draft(0)["mean_draft_mm"] == 0
    with pytest.raises(ValueError):
        v5_upright_draft(-1)


def test_v5_curve_missing_file_or_incompatible_data_is_explicit(monkeypatch):
    monkeypatch.setattr(calculations, "_V5_CAPACITY", None)
    monkeypatch.setattr(calculations, "_V5_CAPACITY_ERROR", "test capacity data unavailable")
    result = v5_upright_draft(458.1)
    assert result["status"] == "unavailable"
    assert result["mean_draft_mm"] is None
    assert result["reason"] == "test capacity data unavailable"


def test_tank_summary_trim_sign_zero_and_transverse():
    stern_deep = tank_reading_summary(36, 34, 30, 30)
    assert stern_deep["measured_trim_mm"] == 5.0           # + = stern deeper
    assert stern_deep["transverse_difference_mm"] == -1.0  # stbd - port
    level = tank_reading_summary(30, 30, 30, 30)
    assert level["measured_trim_mm"] == 0 and level["mean_draft_approx_mm"] == 30
    bow_deep = tank_reading_summary(28, 28, 31, 31)
    assert bow_deep["measured_trim_mm"] == -3.0
    zero = tank_reading_summary(0, 0, 0, 0)                # zero is a valid reading
    assert zero["measured_trim_mm"] == 0 and zero["missing_readings"] == []
    assert level["derived_station_freeboard_mm"]["aft_port"] == 35


def test_tank_summary_missing_reading_keeps_other_outputs():
    r = tank_reading_summary(32, None, 30, 30)
    assert r["mean_aft_mm"] is None and r["measured_trim_mm"] is None
    assert r["mean_forward_mm"] == 30 and r["missing_readings"] == ["aft_stbd"]
    with pytest.raises(ValueError):
        tank_reading_summary(-1, 30, 30, 30)


def test_tank_summary_without_seam_reference_keeps_measurements():
    r = tank_reading_summary(32, 32, 30, 30, seam_height_mm=None)
    assert r["measured_trim_mm"] == 2
    assert r["mean_draft_approx_mm"] == 31
    assert set(r["derived_station_freeboard_mm"].values()) == {None}


def test_draft_prediction_error_signed_and_absolute():
    e = draft_prediction_error(33.6, 35.0)
    assert e["signed_error_mm"] == pytest.approx(1.4) and e["abs_error_mm"] == pytest.approx(1.4)
    assert draft_prediction_error(33.6, 32.0)["signed_error_mm"] == pytest.approx(-1.6)
    assert draft_prediction_error(None, 32.0)["abs_error_mm"] is None


# --- Dry-base weighing basis --------------------------------------------------
# ILLUSTRATIVE masses and positions only, not weighed values.
from calculations import (loading_v5_weighed, loading_match, documented_dry_mass_g,
                          normalise_weighing_basis, ELECTRONICS_ITEM_NAME,
                          WEIGHING_PENDING_REASON,
                          WEIGHING_ELECTRONICS_INCLUDED as INCLUDED,
                          WEIGHING_ELECTRONICS_SEPARATE as SEPARATE,
                          WEIGHING_NOT_RECORDED as NOT_RECORDED)

BASE_NO_ELECTRONICS = {"name": "base", "mass_g": 300.0, "x_mm": -8.0, "y_mm": 0.0, "z_mm": 40.0}
ELECTRONICS = {"mass_g": 30.0, "x_mm": 0.0, "y_mm": 6.0, "z_mm": 70.0}
# The same boat weighed with the electronics on board: combined mass and centre.
BASE_WITH_ELECTRONICS = {"name": "base", "mass_g": 330.0,
                         "x_mm": (300 * -8.0 + 30 * 0.0) / 330,
                         "y_mm": (300 * 0.0 + 30 * 6.0) / 330,
                         "z_mm": (300 * 40.0 + 30 * 70.0) / 330}
CENTRE_VALUES = {"lcg_mm": "lcg_mm_from_midship", "tcg_mm": "tcg_mm", "kg_mm": "kg_mm"}


def _aft_block(mass_g):
    return {**v5_cargo_preset(mass_g, "aft"), "z_mm": 60.0}


@pytest.mark.parametrize("cargo", [[], [_aft_block(250)]], ids=["base only", "250 g aft"])
def test_same_setup_weighed_both_ways_gives_equal_totals(cargo):
    separate = loading_v5_weighed(BASE_NO_ELECTRONICS, cargo, weighing_basis=SEPARATE,
                                  electronics=ELECTRONICS)
    included = loading_v5_weighed(BASE_WITH_ELECTRONICS, cargo, weighing_basis=INCLUDED)
    assert separate["total_mass_g"] == pytest.approx(included["total_mass_g"])
    assert separate["total_mass_g"] == pytest.approx(330.0 + sum(c["mass_g"] for c in cargo))
    for value_key in CENTRE_VALUES.values():
        assert separate[value_key] == pytest.approx(included[value_key])
    assert (v5_upright_draft(separate["total_mass_g"])["mean_draft_mm"]
            == pytest.approx(v5_upright_draft(included["total_mass_g"])["mean_draft_mm"]))


def test_base_only_with_separately_weighed_electronics():
    r = loading_v5_weighed(BASE_NO_ELECTRONICS, [], weighing_basis=SEPARATE,
                           electronics=ELECTRONICS)
    assert r["total_mass_g"] == 330.0
    assert r["included"] == ["base", ELECTRONICS_ITEM_NAME]
    assert v5_upright_draft(r["total_mass_g"])["status"] == "ok"
    # The cargo choice stays independent: one block adds only its own mass.
    for mass in V5_CARGO_PRESETS_G:
        with_block = loading_v5_weighed(BASE_NO_ELECTRONICS, [v5_cargo_preset(mass, "centre")],
                                        weighing_basis=SEPARATE, electronics=ELECTRONICS)
        assert with_block["total_mass_g"] == 330.0 + mass


def test_missing_electronics_mass_makes_total_and_cad_unavailable():
    r = loading_v5_weighed(BASE_NO_ELECTRONICS, [v5_cargo_preset(150, "centre")],
                           weighing_basis=SEPARATE, electronics={**ELECTRONICS, "mass_g": None})
    assert r["total_mass_g"] is None and r["lcg_mm_from_midship"] is None
    assert ELECTRONICS_ITEM_NAME in r["unavailable"]["total_mass_g"]
    cad = v5_upright_draft(r["total_mass_g"])
    assert cad["status"] == "unavailable"
    assert cad["mean_draft_mm"] is None and cad["seam_freeboard_mm"] is None
    # No electronics values at all behaves the same.
    assert loading_v5_weighed(BASE_NO_ELECTRONICS, weighing_basis=SEPARATE)["total_mass_g"] is None
    # Manual draft and trim do not depend on mass inputs.
    assert tank_reading_summary(32, 32, 30, 30)["measured_trim_mm"] == 2


@pytest.mark.parametrize("field, blocked", [("x_mm", "lcg_mm"), ("y_mm", "tcg_mm"),
                                            ("z_mm", "kg_mm")])
def test_missing_electronics_coordinate_only_blocks_its_centre(field, blocked):
    r = loading_v5_weighed(BASE_NO_ELECTRONICS, [], weighing_basis=SEPARATE,
                           electronics={**ELECTRONICS, field: None})
    assert r["total_mass_g"] == 330.0
    assert v5_upright_draft(r["total_mass_g"])["status"] == "ok"
    for key, value_key in CENTRE_VALUES.items():
        if key == blocked:
            assert r[value_key] is None
            assert ELECTRONICS_ITEM_NAME in r["unavailable"][key]
        else:
            assert r[value_key] is not None and key not in r["unavailable"]


def test_included_ignores_stale_electronics_values():
    stale = {"mass_g": 999.0, "x_mm": 90.0, "y_mm": 20.0, "z_mm": 5.0}
    r = loading_v5_weighed(BASE_WITH_ELECTRONICS, [_aft_block(150)], weighing_basis=INCLUDED,
                           electronics=stale)
    assert r["total_mass_g"] == 480.0 and ELECTRONICS_ITEM_NAME not in r["included"]
    assert r == loading_v5_weighed(BASE_WITH_ELECTRONICS, [_aft_block(150)],
                                   weighing_basis=INCLUDED)


def test_not_recorded_basis_leaves_total_and_cad_pending():
    r = loading_v5_weighed(BASE_WITH_ELECTRONICS, [v5_cargo_preset(150, "centre")],
                           weighing_basis=NOT_RECORDED, electronics=ELECTRONICS)
    assert r["total_mass_g"] is None and r["all_outputs_available"] is False
    assert all(r[v] is None for v in CENTRE_VALUES.values()) and r["lcg_mm_from_stern"] is None
    assert set(r["unavailable"].values()) == {WEIGHING_PENDING_REASON}
    assert set(r["unavailable"]) == {"total_mass_g", "lcg_mm", "tcg_mm", "kg_mm"}
    assert v5_upright_draft(r["total_mass_g"])["status"] == "unavailable"
    with pytest.raises(ValueError):
        loading_v5_weighed(BASE_WITH_ELECTRONICS, weighing_basis="included")


def test_missing_or_unknown_weighing_basis_is_not_recorded():
    for value in (None, math.nan, "", "unknown", 3):
        assert normalise_weighing_basis(value) == NOT_RECORDED
    assert normalise_weighing_basis(" electronics_separate ") == SEPARATE


def _record(**overrides):
    record = {"base_weighing_basis": INCLUDED, "assembled_base_mass_g": 330.0,
              "electronics_mass_g": None, "cargo_preset": "250 g", "cargo_mass_g": 251.0,
              "cargo_x_midship_mm": -20.0, "cargo_y_mm": 0.0, "cargo_z_mm": 60.0}
    record.update(overrides)
    return record


BASE_ONLY = {"cargo_preset": "Base only", "cargo_mass_g": 0.0, "cargo_x_midship_mm": None,
             "cargo_y_mm": None, "cargo_z_mm": None}


def test_same_loading_matches_across_weighing_methods():
    weighed_with = _record()
    weighed_without = _record(base_weighing_basis=SEPARATE, assembled_base_mass_g=300.2,
                              electronics_mass_g=29.8)
    assert documented_dry_mass_g(weighed_without) == pytest.approx(330.0)
    assert loading_match(weighed_with, weighed_without) == {"status": "yes", "differs": [],
                                                            "unknown": []}
    assert loading_match(_record(**BASE_ONLY),
                         _record(**BASE_ONLY, base_weighing_basis=SEPARATE,
                                 assembled_base_mass_g=300.0, electronics_mass_g=30.0)
                         )["status"] == "yes"


def test_unknown_load_metadata_is_never_a_confirmed_match():
    older_record = {k: v for k, v in _record().items() if k != "base_weighing_basis"}
    cases = [
        (_record(base_weighing_basis=NOT_RECORDED), "dry boat mass"),
        (older_record, "dry boat mass"),
        (_record(base_weighing_basis=SEPARATE, assembled_base_mass_g=300.0,
                 electronics_mass_g=None), "dry boat mass"),
        (_record(assembled_base_mass_g=None), "dry boat mass"),
        (_record(cargo_z_mm=None), "cargo Z"),
        (_record(cargo_mass_g=math.nan), "cargo mass"),
    ]
    for other, field in cases:
        r = loading_match(_record(), other)
        assert r["status"] == "unknown" and r["unknown"] == [field]
        assert loading_match(other, other)["status"] == "unknown"  # unknown == unknown is not a match


def test_known_load_difference_is_not_a_match():
    assert loading_match(_record(), _record(assembled_base_mass_g=340.0))["differs"] == [
        "dry boat mass"]
    assert loading_match(_record(), _record(cargo_preset="150 g"))["status"] == "no"
    assert loading_match(_record(), _record(cargo_x_midship_mm=0.0))["differs"] == ["cargo X"]
    # Electronics already on the scale and entered again: 360 g, not 330 g.
    double_counted = _record(base_weighing_basis=SEPARATE, electronics_mass_g=30.0)
    assert loading_match(_record(), double_counted)["differs"] == ["dry boat mass"]


# --- 400 g maximum planned cargo (organisers), measured 245 g dry base --------
MEASURED_BASE_245 = {"name": "measured dry base", "mass_g": 245.0,
                     "x_mm": None, "y_mm": None, "z_mm": None}


def test_400_g_case_with_measured_245_g_base_gives_645_g_and_cad_estimate():
    r = loading_v5_weighed(MEASURED_BASE_245, [v5_cargo_preset(400.0, "centre")],
                           weighing_basis=INCLUDED)
    assert r["total_mass_g"] == 645.0
    cad = v5_upright_draft(r["total_mass_g"], 1000.0)
    expected = 45 + 5 * (645.0 - 626.46) / (700.48 - 626.46)    # between CAD table points
    assert cad["status"] == "ok" and cad["mean_draft_mm"] == pytest.approx(expected)
    assert round(cad["mean_draft_mm"], 2) == 46.25
    assert round(cad["seam_freeboard_mm"], 2) == 18.75


def test_cargo_case_is_a_label_and_the_weighed_mass_is_used():
    # A block from the 400 g case that actually weighs 403.5 g.
    weighed = v5_cargo_preset(403.5, "centre")
    r = loading_v5_weighed(MEASURED_BASE_245, [weighed], weighing_basis=INCLUDED)
    assert r["total_mass_g"] == pytest.approx(648.5)
