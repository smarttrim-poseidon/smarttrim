"""SmartTrim rule-based alert explainer.

The alert rules (deterministic, elsewhere) decide WHETHER an alert fires.
This module only explains an alert that has already been decided, using a
fixed rule per alert:

- which supplied facts are the CAUSE of each alert is fixed in ALERT_CAUSE_FACTS;
- RULES fixes the optional CONTEXT facts, the one operator check, and the
  limitations for each alert;
- Python renders every value, unit and sentence, so the explanation cannot
  invent numbers, change the alert, or declare anything safe.

No Streamlit code here: the UI calls explain_alert() and shows result["source"].
No geometry or freeboard numbers live here either: they arrive as facts from
the app.
"""

RULE_SOURCE = "Rule-based explanation"

# PROPOSED operator checks, to be approved by Olga before the evaluation.
OPERATOR_CHECKS = {
    "CHK_NONE": "No action is needed for this alert; continue routine monitoring.",
    # Approved wording (navigation alert): missing depth is the cause.
    "CHK_OBTAIN_DEPTH": ("Verify the charted depth and applicable water-level corrections "
                         "for the next leg. Under-keel clearance has not been assessed."),
    "CHK_REDUCE_LOAD": "Stop adding load and remove the last item before continuing.",
    "CHK_RECENTRE_CARGO": "Move cargo toward the centreline and re-measure the heel.",
    "CHK_REMEASURE_DRAFTS": "Re-measure all four draft readings and fill in any missing reading.",
    "CHK_VERIFY_INPUTS": "Verify the mass and density inputs against the measurement record.",
}

LIMITATIONS = {
    "L_CAD_ESTIMATE": "Geometry values are nominal V3 CAD estimates, not measurements.",
    "L_GEOMETRY_UNVERIFIED": ("The V3 waterplane area is pending verification in SolidWorks, "
                              "so freeboard estimates are illustrative or unavailable."),
    "L_ILLUSTRATIVE": "Some inputs are illustrative, not sourced or measured.",
    "L_UPRIGHT_MODEL": ("Draft is an upright, constant-waterplane-area estimate; "
                        "waves, heel and trim are not modelled."),
    "L_ASSUMED_GM": "Heel uses an assumed GM, not a measured value.",
    "L_MISSING_INPUTS": "Some inputs are missing, so the related outputs are unavailable.",
    "L_AVERAGE_APPROX": "The four-reading average only approximates mean draft when the boat is trimmed.",
}

ALERT_TITLES = {
    "NO_ALERT": "No alert",
    "CLEARANCE_UNASSESSED": "Clearance not assessed",
    "SEAM_FREEBOARD_LOW": "Low estimated seam freeboard",
    "DRAFT_OUT_OF_RANGE": "Draft outside the constant-area model range",
    "HEEL_OVER_DEMO_LIMIT": "Estimated heel above the demonstration limit",
    "DRAFT_MISMATCH": "Predicted and measured draft disagree",
}

# Facts that are the CAUSE of each alert. Every other supplied fact can only be
# context. Fact ids follow the alerts.py vocabulary.
ALERT_CAUSE_FACTS = {
    "NO_ALERT": [],
    "CLEARANCE_UNASSESSED": ["F_DEPTH_MISSING"],
    "SEAM_FREEBOARD_LOW": ["F_SEAM_FREEBOARD", "F_FREEBOARD_MARGIN"],
    "DRAFT_OUT_OF_RANGE": ["F_DRAFT", "F_DRAFT_RANGE"],
    "HEEL_OVER_DEMO_LIMIT": ["F_HEEL", "F_HEEL_LIMIT"],
    "DRAFT_MISMATCH": ["F_DRAFT_PRED", "F_DRAFT_MEAS", "F_READING_MISSING"],
}

# Deterministic rule per alert: (context fact ids, operator check, limitations).
# Causes are always every supplied fact listed in ALERT_CAUSE_FACTS.
RULES = {
    "NO_ALERT": ([], "CHK_NONE", []),
    "CLEARANCE_UNASSESSED": (["F_FB_NEXT"], "CHK_OBTAIN_DEPTH", []),
    "SEAM_FREEBOARD_LOW": ([], "CHK_REDUCE_LOAD", ["L_UPRIGHT_MODEL"]),
    "DRAFT_OUT_OF_RANGE": ([], "CHK_VERIFY_INPUTS", ["L_UPRIGHT_MODEL"]),
    "HEEL_OVER_DEMO_LIMIT": ([], "CHK_RECENTRE_CARGO", ["L_ASSUMED_GM"]),
    "DRAFT_MISMATCH": ([], "CHK_REMEASURE_DRAFTS", ["L_AVERAGE_APPROX"]),
}

_SELECTION_KEYS = ("cause_fact_ids", "context_fact_ids", "operator_check_id", "limitation_ids")


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------
def _validate_alert(alert):
    if not isinstance(alert, dict):
        raise ValueError("alert must be a dict")
    alert_id = alert.get("alert_id")
    if alert_id not in RULES:
        raise ValueError(f"unknown alert_id: {alert_id!r}")
    facts = alert.get("facts", [])
    if not isinstance(facts, list):
        raise ValueError("facts must be a list")
    seen = set()
    for fact in facts:
        if not isinstance(fact, dict):
            raise ValueError("each fact must be a dict")
        for key in ("id", "label", "unit", "provenance"):
            if not isinstance(fact.get(key), str):
                raise ValueError(f"fact {fact.get('id')!r}: '{key}' must be a string")
        if "value" not in fact:
            raise ValueError(f"fact {fact['id']!r}: 'value' must be supplied (None if missing)")
        value = fact["value"]
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError(f"fact {fact['id']!r}: value must be a number or None")
        if fact["id"] in seen:
            raise ValueError(f"duplicate fact id: {fact['id']!r}")
        seen.add(fact["id"])
    missing = alert.get("missing_inputs", [])
    if not isinstance(missing, list) or not all(isinstance(m, str) for m in missing):
        raise ValueError("missing_inputs must be a list of strings")
    return alert_id, facts, missing


# ---------------------------------------------------------------------------
# Rule-based selection
# ---------------------------------------------------------------------------
def rule_based_selection(alert):
    """Deterministic selection of causes, context, operator check and limitations.

    Context facts must carry a value: a missing value can be a cause, not a comparison.
    """
    alert_id, facts, missing = _validate_alert(alert)
    cause_ids = [f["id"] for f in facts if f["id"] in ALERT_CAUSE_FACTS[alert_id]]
    preferred_context, check_id, limitations = RULES[alert_id]
    context = [f["id"] for f in facts
               if f["id"] in preferred_context and f["value"] is not None]
    lims = list(limitations)
    if any(fid.startswith("F_FB") for fid in context):  # a freeboard estimate is shown
        lims.append("L_UPRIGHT_MODEL")
    provenances = " ".join(f["provenance"].lower() for f in facts)
    if missing:
        lims.append("L_MISSING_INPUTS")
    if "cad" in provenances:
        lims.append("L_CAD_ESTIMATE")
    if "illustrative" in provenances:
        lims.append("L_ILLUSTRATIVE")
    if "unverified" in provenances or "pending" in provenances:
        lims.append("L_GEOMETRY_UNVERIFIED")
    if alert_id == "NO_ALERT":
        lims = []
    return {"alert_id": alert_id,
            "cause_fact_ids": cause_ids,
            "context_fact_ids": context,
            "operator_check_id": check_id,
            "limitation_ids": [l for l in LIMITATIONS if l in lims]}


# ---------------------------------------------------------------------------
# Rendering (all text and numbers come from Python)
# ---------------------------------------------------------------------------
def _format_fact(fact):
    value = fact["value"]
    if value is None:
        note = "" if fact["provenance"].lower() == "missing" else f" ({fact['provenance']})"
        return f"{fact['label']}: missing{note}"
    shown = f"{round(value, 2):g} {fact['unit']}".strip()
    return f"{fact['label']}: {shown} ({fact['provenance']})"


def render_explanation(alert, selection):
    alert_id, facts, missing = _validate_alert(alert)
    by_id = {f["id"]: f for f in facts}
    leg = alert.get("route_leg")
    lines = [ALERT_TITLES[alert_id] + (f" on {leg}" if leg else "") + "."]
    if selection["cause_fact_ids"]:
        lines.append("Cause:")
        lines += ["- " + _format_fact(by_id[fid]) for fid in selection["cause_fact_ids"]]
    if selection["context_fact_ids"]:
        lines.append("Context (does not trigger this alert):")
        lines += ["- " + _format_fact(by_id[fid]) for fid in selection["context_fact_ids"]]
    lines.append("Next check: " + OPERATOR_CHECKS[selection["operator_check_id"]])
    lims = [LIMITATIONS[l] for l in selection["limitation_ids"]]
    if lims:
        lines.append("Limitations: " + " ".join(lims))
    if missing:  # always shown
        lines.append("Missing inputs: " + "; ".join(missing) + ".")
    return "\n".join(lines)


def explain_alert(alert):
    """Explain one already-decided alert with its fixed rule.

    alert: {"alert_id", "route_leg", "facts": [{"id", "label", "value", "unit",
    "provenance"}], "missing_inputs": [str]} built by the app from current data.
    Raises ValueError for malformed alerts (programming errors).
    """
    selection = rule_based_selection(alert)
    return {
        "source": RULE_SOURCE,
        "alert_id": selection["alert_id"],
        "route_leg": alert.get("route_leg"),
        **{k: selection[k] for k in _SELECTION_KEYS},
        "text": render_explanation(alert, selection),
    }
