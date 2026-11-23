import json

import pytest

import alert_explainer
from alert_explainer import RULE_SOURCE, explain_alert, rule_based_selection

# ---------------------------------------------------------------------------
# Fixtures. ILLUSTRATIVE ONLY: total mass 500 g, densities 1025 / 1000 kg/m^3,
# and an ASSUMED waterplane area of 8,728 mm^2 per pontoon x 2. Olga has
# confirmed V3 for printing, but its waterplane area is still pending
# verification in SolidWorks, so these freeboards (37.06 -> 36.36 mm) are not
# V3 results. The explainer only uses the facts passed in, so the app can
# supply new numbers once the area is verified.
# ---------------------------------------------------------------------------
ILLUSTRATIVE = "Illustrative estimate — V3 waterplane area unverified"

NEXT_LEG = {
    "alert_id": "CLEARANCE_UNASSESSED",
    "route_leg": "Leg 2 (river)",
    "facts": [
        {"id": "F_FB_CURRENT", "label": "Estimated seam freeboard, leg 1 (sea)",
         "value": 37.06, "unit": "mm", "provenance": ILLUSTRATIVE},
        {"id": "F_FB_NEXT", "label": "Estimated seam freeboard, leg 2 (river)",
         "value": 36.36, "unit": "mm", "provenance": ILLUSTRATIVE},
        {"id": "F_DEPTH_MISSING", "label": "Water depth, leg 2",
         "value": None, "unit": "m", "provenance": "missing"},
        {"id": "F_HEEL", "label": "Estimated heel", "value": 0.0, "unit": "deg",
         "provenance": "assumed GM"},
        {"id": "F_DENSITY", "label": "Water density, leg 2", "value": 1000,
         "unit": "kg/m^3", "provenance": "illustrative"},
    ],
    "missing_inputs": ["water depth, leg 2"],
}

# Same alert for V3 with no freeboard estimate available yet.
NEXT_LEG_V3_PENDING = {
    "alert_id": "CLEARANCE_UNASSESSED",
    "route_leg": "Leg 2 (river)",
    "facts": [
        {"id": "F_DEPTH_MISSING", "label": "Water depth, leg 2",
         "value": None, "unit": "m", "provenance": "missing"},
        {"id": "F_WATERPLANE_AREA", "label": "V3 waterplane area per pontoon",
         "value": None, "unit": "mm^2", "provenance": "pending SolidWorks verification"},
        {"id": "F_DENSITY", "label": "Water density, leg 2", "value": 1000,
         "unit": "kg/m^3", "provenance": "illustrative"},
    ],
    "missing_inputs": ["water depth, leg 2",
                       "V3 waterplane area (pending SolidWorks verification)"],
}

NORMAL = {"alert_id": "NO_ALERT", "route_leg": "Leg 1 (sea)",
          "facts": [{"id": "F_SEAM_FREEBOARD", "label": "Estimated seam freeboard",
                     "value": 37.06, "unit": "mm", "provenance": ILLUSTRATIVE}],
          "missing_inputs": []}

HEEL = {"alert_id": "HEEL_OVER_DEMO_LIMIT", "route_leg": None,
        "facts": [{"id": "F_HEEL", "label": "Estimated heel", "value": 9.4, "unit": "deg",
                   "provenance": "assumed GM 70 mm"},
                  {"id": "F_HEEL_LIMIT", "label": "Demonstration heel limit", "value": 8,
                   "unit": "deg", "provenance": "demo threshold"},
                  {"id": "F_SEAM_FREEBOARD", "label": "Estimated seam freeboard",
                   "value": 36.36, "unit": "mm", "provenance": ILLUSTRATIVE}],
        "missing_inputs": []}

DEPTH_ONLY = {"alert_id": "CLEARANCE_UNASSESSED", "route_leg": "Leg 2 (river)",
              "facts": [{"id": "F_DEPTH_MISSING", "label": "Water depth, leg 2",
                         "value": None, "unit": "m", "provenance": "missing"}],
              "missing_inputs": ["water depth, leg 2"]}

# The alert exactly as the dashboard builds it when no water depth is entered.
APP_MISSING_DEPTH = {"alert_id": "CLEARANCE_UNASSESSED",
                     "route_leg": "Tank test / selected water",
                     "facts": [{"id": "F_DEPTH_MISSING", "label": "Water depth", "value": None,
                                "unit": "m", "provenance": "not entered"}],
                     "missing_inputs": ["water depth"]}

CONFLICT = {"alert_id": "DRAFT_MISMATCH", "route_leg": None,
            "facts": [{"id": "F_DRAFT_PRED", "label": "Predicted mean draft", "value": 28.64,
                       "unit": "mm", "provenance": ILLUSTRATIVE},
                      {"id": "F_DRAFT_MEAS", "label": "Measured mean draft (3 of 4 readings)",
                       "value": 33.0, "unit": "mm", "provenance": "measured, tap water"},
                      {"id": "F_READING_MISSING", "label": "Fwd stbd draft reading",
                       "value": None, "unit": "mm", "provenance": "missing"}],
            "missing_inputs": ["fwd stbd draft reading"]}

APPROVED_DEPTH_CHECK = ("Next check: Verify the charted depth and applicable water-level "
                        "corrections for the next leg. Under-keel clearance has not been assessed.")


# --- Missing-depth alert (the dashboard's alert) -----------------------------
def test_app_missing_depth_alert_is_rule_based_with_approved_check():
    r = explain_alert(APP_MISSING_DEPTH)
    assert r["source"] == RULE_SOURCE == "Rule-based explanation"
    assert r["alert_id"] == "CLEARANCE_UNASSESSED"
    assert r["cause_fact_ids"] == ["F_DEPTH_MISSING"]          # depth is the cause
    assert r["context_fact_ids"] == []
    assert r["operator_check_id"] == "CHK_OBTAIN_DEPTH"
    assert r["text"] == (
        "Clearance not assessed on Tank test / selected water.\n"
        "Cause:\n- Water depth: missing (not entered)\n"
        + APPROVED_DEPTH_CHECK + "\n"
        "Limitations: Some inputs are missing, so the related outputs are unavailable.\n"
        "Missing inputs: water depth.")


def test_clearance_alert_uses_approved_wording_in_every_case():
    for alert in (NEXT_LEG, NEXT_LEG_V3_PENDING, DEPTH_ONLY, APP_MISSING_DEPTH):
        r = explain_alert(alert)
        assert r["source"] == RULE_SOURCE
        assert r["operator_check_id"] == "CHK_OBTAIN_DEPTH"
        assert r["cause_fact_ids"] == ["F_DEPTH_MISSING"]
        assert APPROVED_DEPTH_CHECK in r["text"]


def test_cause_and_context_are_separated():
    r = explain_alert(NEXT_LEG)
    assert r["cause_fact_ids"] == ["F_DEPTH_MISSING"]
    assert r["context_fact_ids"] == ["F_FB_NEXT"]
    assert "Cause:\n- Water depth, leg 2: missing\n" in r["text"]
    assert ("Context (does not trigger this alert):\n- Estimated seam freeboard, leg 2 "
            "(river): 36.36 mm (" + ILLUSTRATIVE + ")") in r["text"]
    assert "Estimated heel" not in r["text"]                      # distractor left out


def test_explainer_uses_facts_passed_by_app():
    updated = json.loads(json.dumps(NEXT_LEG))
    updated["facts"][1].update(value=35.1, provenance="V3 CAD estimate, area verified")
    r = explain_alert(updated)
    assert "leg 2 (river): 35.1 mm (V3 CAD estimate, area verified)" in r["text"]
    assert "36.36" not in r["text"]


def test_pending_case_never_uses_missing_value_as_context():
    r = explain_alert(NEXT_LEG_V3_PENDING)
    assert r["context_fact_ids"] == [] and "Context" not in r["text"]
    assert "pending verification in SolidWorks" in r["text"]
    assert "V3 waterplane area (pending SolidWorks verification)" in r["text"]


def test_missing_inputs_always_rendered():
    for alert in (NEXT_LEG, DEPTH_ONLY, APP_MISSING_DEPTH):
        assert "Missing inputs: " in explain_alert(alert)["text"]


def test_result_has_no_model_fields():
    r = explain_alert(APP_MISSING_DEPTH)
    assert set(r) == {"source", "alert_id", "route_leg", "cause_fact_ids",
                      "context_fact_ids", "operator_check_id", "limitation_ids", "text"}
    assert not hasattr(alert_explainer, "AI_SOURCE")


# --- Rule-based selection for each alert ---------------------------------------
@pytest.mark.parametrize("alert, causes, context, check, lims", [
    (NORMAL, [], [], "CHK_NONE", []),
    (HEEL, ["F_HEEL", "F_HEEL_LIMIT"], [], "CHK_RECENTRE_CARGO",
     ["L_GEOMETRY_UNVERIFIED", "L_ILLUSTRATIVE", "L_ASSUMED_GM"]),
    (DEPTH_ONLY, ["F_DEPTH_MISSING"], [], "CHK_OBTAIN_DEPTH", ["L_MISSING_INPUTS"]),
    (CONFLICT, ["F_DRAFT_PRED", "F_DRAFT_MEAS", "F_READING_MISSING"], [], "CHK_REMEASURE_DRAFTS",
     ["L_GEOMETRY_UNVERIFIED", "L_ILLUSTRATIVE", "L_MISSING_INPUTS", "L_AVERAGE_APPROX"]),
    (NEXT_LEG, ["F_DEPTH_MISSING"], ["F_FB_NEXT"], "CHK_OBTAIN_DEPTH",
     ["L_GEOMETRY_UNVERIFIED", "L_ILLUSTRATIVE", "L_UPRIGHT_MODEL", "L_MISSING_INPUTS"]),
    (NEXT_LEG_V3_PENDING, ["F_DEPTH_MISSING"], [], "CHK_OBTAIN_DEPTH",
     ["L_GEOMETRY_UNVERIFIED", "L_ILLUSTRATIVE", "L_MISSING_INPUTS"]),
])
def test_rule_based_selection(alert, causes, context, check, lims):
    sel = rule_based_selection(alert)
    assert sel["cause_fact_ids"] == causes and sel["context_fact_ids"] == context
    assert sel["operator_check_id"] == check and sel["limitation_ids"] == lims


def test_every_rule_check_has_wording():
    for _, check, _ in alert_explainer.RULES.values():
        assert check in alert_explainer.OPERATOR_CHECKS


# --- Input validation (programming errors still raise) -----------------------
@pytest.mark.parametrize("bad", [
    {"alert_id": "MADE_UP", "facts": []},
    {**NEXT_LEG, "facts": NEXT_LEG["facts"] + [NEXT_LEG["facts"][0]]},          # duplicate id
    {**NEXT_LEG, "facts": [{"id": "F_X", "label": "x", "unit": "mm", "provenance": "p"}]},
    {**NEXT_LEG, "facts": [{"id": "F_X", "label": "x", "value": "12", "unit": "mm",
                            "provenance": "p"}]},
])
def test_invalid_alert_input_raises(bad):
    with pytest.raises(ValueError):
        explain_alert(bad)
