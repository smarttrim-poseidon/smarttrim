"""Transparent first-pass SmartTrim estimates, not certified naval architecture."""
import json
from math import atan, degrees, isfinite
from pathlib import Path

# Geometry is an estimate from the printed shape; calibrate after tank testing.
HULL_LENGTH_M = 0.200
HULL_WIDTH_M = 0.048
HULL_WATERPLANE_AREA_M2 = 0.008728
HULL_COUNT = 2
MAX_HEIGHT_M = 0.052


def displacement_and_draft(ship_g, cargo, density_kg_m3=1000.0):
    if density_kg_m3 <= 0 or ship_g < 0:
        raise ValueError("Mass and density must be valid")
    if any(item["mass_g"] < 0 for item in cargo):
        raise ValueError("Cargo masses must be nonnegative")
    total_g = ship_g + sum(item["mass_g"] for item in cargo)
    displaced_m3 = total_g / 1000 / density_kg_m3
    plane_m2 = HULL_COUNT * HULL_WATERPLANE_AREA_M2
    draft_m = displaced_m3 / plane_m2
    return {"total_g": total_g, "displaced_l": displaced_m3 * 1000,
            "draft_mm": draft_m * 1000, "freeboard_mm": (MAX_HEIGHT_M - draft_m) * 1000,
            "over_capacity": draft_m >= MAX_HEIGHT_M}


def loading_cg(ship_g, cargo, gm_m=0.07):
    """Approximate equilibrium heel for small angles, using an assumed GM.

    Vessel's own centre of mass is assumed at y=0. Not valid at large heel.
    """
    total = ship_g + sum(i["mass_g"] for i in cargo)
    if total <= 0 or gm_m <= 0:
        raise ValueError("Total mass and assumed GM must be positive")
    y_cg_m = sum(i["mass_g"] * i["y_mm"] / 1000 for i in cargo) / total
    heel_deg = degrees(atan(y_cg_m / gm_m))
    return {"y_cg_mm": y_cg_m * 1000, "heel_deg": heel_deg,
            "gm_assumed_mm": gm_m * 1000}


# ---------------------------------------------------------------------------
# V2 loading model: combined centre of mass from caller-supplied items.
#
# Coordinate system (Olga's): X = 0 mm at the stern, increasing towards the bow
# (200 mm); Y negative to port, positive to starboard; Z = 0 mm at the bottom of
# the pontoons, increasing upward. Masses in grams, positions in millimetres.
#
# No masses or positions are hardcoded here. Unknown values are None and are
# never replaced by zero. NaN (e.g. an empty editable table cell) counts as None.
# ---------------------------------------------------------------------------
_V2_FIELDS = ("mass_g", "x_mm", "y_mm", "z_mm")
_V2_CENTRES = (("lcg_mm", "x_mm"), ("tcg_mm", "y_mm"), ("kg_mm", "z_mm"))


def _v2_value(item, field, label):
    if field not in item:
        raise ValueError(f"{label}: '{field}' must be supplied (use None if unknown)")
    value = item[field]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}: '{field}' must be a number or None")
    if value != value:  # NaN
        return None
    if field == "mass_g" and value < 0:
        raise ValueError(f"{label}: mass_g must be nonnegative")
    return float(value)


def loading_v2(structure, items=()):
    """Total mass and combined LCG, TCG and KG of the structure plus items.

    structure and each entry of items is a dict with keys name (optional),
    mass_g, x_mm, y_mm, z_mm (each a number or None) and included (optional,
    default True). Excluded items are listed but take no part in the result.

    Missing-value rules:
    - any unknown mass on an included item -> total mass and all centres None;
    - an unknown coordinate on an included item with positive mass -> only that
      centre is None; a zero-mass item's coordinates do not matter;
    - zero total mass -> centres None (undefined).
    """
    entries = [("structure", structure)] + [(f"item[{i}]", it) for i, it in enumerate(items)]
    rows, missing, included_names, excluded_names = [], [], [], []
    for default_name, item in entries:
        if not isinstance(item, dict):
            raise ValueError(f"{default_name}: each entry must be a dict")
        name = item.get("name") or default_name
        values = {f: _v2_value(item, f, name) for f in _V2_FIELDS}
        if not item.get("included", True):
            excluded_names.append(name)
            continue
        included_names.append(name)
        missing += [f"{name}.{f}" for f in _V2_FIELDS if values[f] is None]
        rows.append((name, values))

    unavailable = {}
    masses = [v["mass_g"] for _, v in rows]
    if any(m is None for m in masses):
        total_g = None
        unknown = [n for n, v in rows if v["mass_g"] is None]
        unavailable["total_mass_g"] = "unknown mass: " + ", ".join(unknown)
    else:
        total_g = sum(masses)

    centres = {}
    for key, field in _V2_CENTRES:
        blockers = [n for n, v in rows if v[field] is None
                    and (v["mass_g"] is None or v["mass_g"] > 0)]
        if total_g is None:
            centres[key] = None
            unavailable[key] = "total mass unavailable"
        elif blockers:
            centres[key] = None
            unavailable[key] = f"unknown {field}: " + ", ".join(blockers)
        elif total_g == 0:
            centres[key] = None
            unavailable[key] = "total mass is zero"
        else:
            centres[key] = sum(v["mass_g"] * v[field] for _, v in rows
                               if v["mass_g"] > 0) / total_g

    return {"total_mass_g": total_g, **centres,
            "all_outputs_available": not unavailable,
            "missing": missing, "unavailable": unavailable,
            "included": included_names, "excluded": excluded_names}


def measured_trim_mm(draft_aft_mm, draft_forward_mm):
    """Trim from two measured drafts: aft draft minus forward draft, in mm.

    Positive means the stern sits deeper; negative means the bow sits deeper.
    Returns None if either reading is None or NaN (missing). Zero is a valid
    reading. Negative or non-numeric readings raise ValueError.
    """
    readings = []
    for label, value in (("draft_aft_mm", draft_aft_mm),
                         ("draft_forward_mm", draft_forward_mm)):
        if value is None or (isinstance(value, float) and value != value):
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label} must be a number or None")
        if value < 0:
            raise ValueError(f"{label} must be nonnegative")
        readings.append(value)
    return readings[0] - readings[1]


# ---------------------------------------------------------------------------
# V2 mean draft and freeboard from caller-supplied geometry.
#
# Nothing V2-specific is hardcoded: the V1 constants above are not used here.
# Units: grams, mm^2 (waterplane area per hull), mm, kg/m^3. Unknown inputs are
# None (NaN counts as None) and are never replaced by zero.
# ---------------------------------------------------------------------------
CONSTANT_AREA_DRAFT_BASIS = ("constant-area estimate: one waterplane area per "
                             "hull, assumed constant with draft (wall-sided)")


def _v2_number(value, label, positive=False, integer=False):
    if value is None or (isinstance(value, float) and value != value):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number or None")
    if integer and value != int(value):
        raise ValueError(f"{label} must be a whole number")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{label} must be {'positive' if positive else 'nonnegative'}")
    return value


def draft_freeboard_v2(*, total_mass_g, waterplane_area_per_hull_mm2,
                       hull_count, freeboard_reference_height_mm,
                       density_kg_m3):
    """Level-keel mean draft and freeboard for caller-supplied V2 geometry.

    All arguments are keyword-only and required; pass None when unknown.
    total_mass_g can be loading_v2(...)["total_mass_g"].

    - mean draft needs mass, area, hull count and density;
    - freeboard (reference height minus mean draft) also needs the height;
      a missing height leaves the draft available.
    """
    inputs = {
        "total_mass_g": _v2_number(total_mass_g, "total_mass_g"),
        "waterplane_area_per_hull_mm2": _v2_number(
            waterplane_area_per_hull_mm2, "waterplane_area_per_hull_mm2", positive=True),
        "hull_count": _v2_number(hull_count, "hull_count", positive=True, integer=True),
        "freeboard_reference_height_mm": _v2_number(
            freeboard_reference_height_mm, "freeboard_reference_height_mm", positive=True),
        "density_kg_m3": _v2_number(density_kg_m3, "density_kg_m3", positive=True),
    }
    missing = [k for k, v in inputs.items() if v is None]
    draft_needs = [k for k in missing if k != "freeboard_reference_height_mm"]
    unavailable = {}

    if draft_needs:
        draft_mm = None
        unavailable["mean_draft_mm"] = "unknown: " + ", ".join(draft_needs)
    else:
        displaced_mm3 = inputs["total_mass_g"] / 1000 / inputs["density_kg_m3"] * 1e9
        plane_mm2 = inputs["hull_count"] * inputs["waterplane_area_per_hull_mm2"]
        draft_mm = displaced_mm3 / plane_mm2

    height = inputs["freeboard_reference_height_mm"]
    if draft_mm is None or height is None:
        freeboard_mm = reaches = None
        unavailable["freeboard_mm"] = ("mean draft unavailable" if draft_mm is None
                                       else "unknown: freeboard_reference_height_mm")
    else:
        freeboard_mm = height - draft_mm
        reaches = draft_mm >= height

    return {"mean_draft_mm": draft_mm,
            "draft_basis": CONSTANT_AREA_DRAFT_BASIS if draft_mm is not None else None,
            "freeboard_mm": freeboard_mm,
            "draft_reaches_reference_height": reaches,
            "all_outputs_available": not unavailable,
            "missing": missing, "unavailable": unavailable}


# ---------------------------------------------------------------------------
# V2 mean draft and seam freeboard (geometry confirmed by Olga, nominal CAD).
#
# These values are for the handoff only. They are NOT defaults: the caller must
# pass every input. The draft range is where Olga reports the waterplane area
# is approximately constant; it qualifies the estimate and is not an offset.
# ---------------------------------------------------------------------------
V2_NOMINAL_CAD_GEOMETRY = {
    "waterplane_area_per_pontoon_m2": 0.008728,  # nominal CAD, per pontoon
    "pontoon_count": 2,                          # nominal CAD
    "seam_height_mm": 65.0,                      # nominal CAD seam reference
}
V2_CONSTANT_AREA_DRAFT_RANGE_MM = (2.4, 65.0)    # Olga: area ~constant here
V2_SEAM_DRAFT_BASIS = "upright, constant-waterplane-area estimate"


def draft_seam_freeboard_v2(*, total_mass_g, density_kg_m3,
                            waterplane_area_per_pontoon_m2, pontoon_count,
                            seam_height_mm):
    """Upright mean draft and seam freeboard for the V2 pontoons.

    All arguments are keyword-only and required; pass None when unknown.
    displaced volume = mass (kg) / density; mean draft = displaced volume /
    (area per pontoon x pontoon count); seam freeboard = seam height - draft.

    Blocking: displaced volume needs mass and density; mean draft also needs
    area and pontoon count; seam freeboard also needs the seam height.
    """
    inputs = {
        "total_mass_g": _v2_number(total_mass_g, "total_mass_g"),
        "density_kg_m3": _v2_number(density_kg_m3, "density_kg_m3", positive=True),
        "waterplane_area_per_pontoon_m2": _v2_number(
            waterplane_area_per_pontoon_m2, "waterplane_area_per_pontoon_m2", positive=True),
        "pontoon_count": _v2_number(pontoon_count, "pontoon_count",
                                    positive=True, integer=True),
        "seam_height_mm": _v2_number(seam_height_mm, "seam_height_mm", positive=True),
    }
    missing = [k for k, v in inputs.items() if v is None]
    unavailable, flags = {}, []

    def _needs(output, names):
        unknown = [n for n in names if inputs[n] is None]
        if unknown:
            unavailable[output] = "unknown: " + ", ".join(unknown)
        return not unknown

    volume_inputs = ["total_mass_g", "density_kg_m3"]
    draft_inputs = volume_inputs + ["waterplane_area_per_pontoon_m2", "pontoon_count"]
    seam_inputs = draft_inputs + ["seam_height_mm"]

    volume_m3 = draft_mm = freeboard_mm = None
    in_range = seam_status = reaches = None
    if _needs("displaced_volume_m3", volume_inputs):
        volume_m3 = inputs["total_mass_g"] / 1000 / inputs["density_kg_m3"]
    if _needs("mean_draft_mm", draft_inputs):
        combined_m2 = inputs["waterplane_area_per_pontoon_m2"] * inputs["pontoon_count"]
        draft_mm = volume_m3 / combined_m2 * 1000
        low, high = V2_CONSTANT_AREA_DRAFT_RANGE_MM
        in_range = low <= draft_mm <= high
        if draft_mm < low:
            flags.append(f"mean draft below {low} mm: outside the constant-area range")
        elif draft_mm > high:
            flags.append(f"mean draft above {high} mm: outside the constant-area range")
    else:
        unavailable["within_constant_area_range"] = "mean draft unavailable"
    if _needs("seam_freeboard_mm", seam_inputs):
        freeboard_mm = inputs["seam_height_mm"] - draft_mm
        reaches = draft_mm >= inputs["seam_height_mm"]
        if draft_mm > inputs["seam_height_mm"]:
            seam_status = "exceeds nominal seam (upright model)"
        elif reaches:
            seam_status = "reaches nominal seam (upright model)"
        else:
            seam_status = "below nominal seam (upright model)"
        if reaches:
            flags.append(seam_status)
    else:
        unavailable["seam_status"] = "seam freeboard unavailable"

    return {"displaced_volume_m3": volume_m3,
            "mean_draft_mm": draft_mm,
            "seam_freeboard_mm": freeboard_mm,
            "draft_basis": V2_SEAM_DRAFT_BASIS if draft_mm is not None else None,
            "within_constant_area_range": in_range,
            "constant_area_range_mm": V2_CONSTANT_AREA_DRAFT_RANGE_MM,
            "reaches_or_exceeds_seam": reaches,
            "seam_status": seam_status,
            "flags": flags,
            "all_outputs_available": not unavailable,
            "missing": missing, "unavailable": unavailable}


# ---------------------------------------------------------------------------
# V5 (printing now). Midpoint coordinates, CAD displacement curve, tank readings.
#
# V5 coordinates (CAD and dashboard input): x = -100 mm at the stern, 0 at
# midship, +100 at the bow; y positive to starboard; z up from the hull bottom.
# loading_v2 historically used x from the stern (0..200). loading_v5 converts
# every x exactly once, at its entry, with x_stern = x_midship + 100.
# ---------------------------------------------------------------------------
V5_HALF_LENGTH_MM = 100.0
V5_SEAM_HEIGHT_MM = 65.0
V5_PONTOON_SPACING_MM = 120.0
V5_CORE_PRINT_MASS_G = None           # loaded from attributed nominal CAD data below
V5_PLASTIC_COM_MIDSHIP_MM = (-8.03, 0.0, 49.8)   # CAD, plastic only, midship origin
V5_DRAFT_STATIONS_MIDSHIP_MM = (-75.0, 75.0)     # aft and forward marks (V5 README F)
V5_ESTIMATE_LABEL = "Estimated from nominal V5 CAD · upright still water"

# Cargo case labels (one block at a time, never summed). 400 g is the organisers'
# maximum planned cargo. The loading always uses the weighed mass entered.
V5_CARGO_PRESETS_G = (150.0, 250.0, 350.0, 400.0)
V5_CARGO_POSITIONS_MIDSHIP_MM = {      # starting points; edit to the actual X/Y/Z
    "centre": (0.0, 0.0),
    "aft": (-20.0, 0.0),
    "starboard": (0.0, 20.0),
}

def _optional_number(value, label, *, positive=False):
    """None/NaN -> None; numbers pass; anything else raises ValueError."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number or None")
    if not isfinite(value):
        if value != value:
            return None
        raise ValueError(f"{label} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{label} must be positive")
    return float(value)


def _load_v5_capacity(path):
    """Load and validate the small, attributed subset of the V5 CAD JSON."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"could not read V5 capacity data: {exc}"

    if not isinstance(payload, dict):
        return None, "V5 capacity data must be a JSON object"
    expected_units = {"draft": "mm", "displacement": "freshwater_displacement_g"}
    if payload.get("units") != expected_units:
        return None, "V5 capacity data has missing or incompatible units"
    if payload.get("covers") != "both pontoons together":
        return None, "V5 capacity data does not confirm both pontoons are represented"

    try:
        reference_density = _optional_number(
            payload.get("reference_water_density_kg_m3"),
            "reference_water_density_kg_m3",
            positive=True,
        )
        rows = payload["capacity_still_water"]
        if not isinstance(rows, list) or len(rows) < 2:
            raise ValueError("capacity_still_water must contain at least two points")
        table = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"capacity point {index} must be an object")
            draft = _optional_number(row.get("draft_mm"), f"point {index} draft_mm")
            displacement = _optional_number(
                row.get("freshwater_displacement_g"),
                f"point {index} freshwater_displacement_g",
            )
            if draft is None or displacement is None or draft < 0 or displacement < 0:
                raise ValueError(f"capacity point {index} has missing or negative values")
            if table and (draft <= table[-1][0] or displacement <= table[-1][1]):
                raise ValueError("capacity points must increase in draft and displacement")
            table.append((draft, displacement))
        if reference_density is None:
            raise ValueError("reference water density is missing")
        required_text = ("source_file", "source_field", "cad_revision", "status")
        if any(not isinstance(payload.get(key), str) or not payload[key].strip()
               for key in required_text):
            raise ValueError("V5 capacity data is missing source or revision metadata")
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"incompatible V5 capacity data: {exc}"

    return {
        "data": payload,
        "table": tuple(table),
        "reference_density_kg_m3": reference_density,
    }, None


_V5_CAPACITY, _V5_CAPACITY_ERROR = _load_v5_capacity(
    Path(__file__).with_name("v5_capacity.json")
)
if _V5_CAPACITY is None:
    V5_CAPACITY_TABLE = ()
    V5_CAPACITY_SOURCE = {}
else:
    _v5_data = _V5_CAPACITY["data"]
    V5_CAPACITY_TABLE = _V5_CAPACITY["table"]
    V5_CAPACITY_SOURCE = {
        "source": f"{_v5_data['source_file']} · {_v5_data['source_field']}",
        "revision": _v5_data["cad_revision"],
        "reference_density_kg_m3": _V5_CAPACITY["reference_density_kg_m3"],
        "reference_density_source": _v5_data["reference_density_source"],
        "covers": _v5_data["covers"],
        "status": _v5_data["status"],
        "table_bounds_mm": (V5_CAPACITY_TABLE[0][0], V5_CAPACITY_TABLE[-1][0]),
        "table_bounds_displacement_g": (
            V5_CAPACITY_TABLE[0][1], V5_CAPACITY_TABLE[-1][1]
        ),
    }
    V5_CORE_PRINT_MASS_G = _optional_number(
        _v5_data.get("core_print_mass_g"), "core_print_mass_g", positive=True
    )


def midship_to_stern_x(x_midship_mm):
    """V5 midship-origin x (-100..+100) to stern-origin x (0..200). None stays None."""
    x = _optional_number(x_midship_mm, "x_midship_mm")
    return None if x is None else x + V5_HALF_LENGTH_MM


def stern_to_midship_x(x_stern_mm):
    x = _optional_number(x_stern_mm, "x_stern_mm")
    return None if x is None else x - V5_HALF_LENGTH_MM


def v5_cargo_preset(mass_g, position):
    """One editable cargo block. Presets are alternatives, never summed."""
    if position not in V5_CARGO_POSITIONS_MIDSHIP_MM:
        raise ValueError(f"unknown position {position!r}")
    x, y = V5_CARGO_POSITIONS_MIDSHIP_MM[position]
    mass = _optional_number(mass_g, "mass_g")
    name = f"{mass:g} g {position}" if mass is not None else f"unknown mass {position}"
    return {"name": name, "mass_g": mass,
            "x_mm": x, "y_mm": y, "z_mm": None,
            "provenance": "preset start position — edit to the actual X/Y/Z"}


def loading_v5(base, items=()):
    """loading_v2 for V5 inputs given in midship coordinates.

    base and items use the loading_v2 fields (mass_g, x_mm, y_mm, z_mm, name,
    included) with x measured from midship. X is converted to the stern origin
    once here; the result reports LCG in both origins, clearly labelled.
    """
    def to_stern(entry):
        if not isinstance(entry, dict):
            raise ValueError("each entry must be a dict")
        converted = dict(entry)
        if "x_mm" in entry:
            converted["x_mm"] = midship_to_stern_x(entry["x_mm"])
        return converted

    result = loading_v2(to_stern(base), [to_stern(i) for i in items])
    lcg_stern = result.pop("lcg_mm")
    result.update({
        "lcg_mm_from_stern": lcg_stern,
        "lcg_mm_from_midship": None if lcg_stern is None else lcg_stern - V5_HALF_LENGTH_MM,
        "input_x_origin": "midship (x=-100 stern, 0 midship, +100 bow)",
    })
    return result


# ---------------------------------------------------------------------------
# Dry-base weighing basis. The dry assembled base is weighed either with the
# Nano, MPU6050 and wiring on board ("included") or without them, with the
# electronics weighed on their own ("separate"). Each mass is counted once.
# ---------------------------------------------------------------------------
WEIGHING_ELECTRONICS_INCLUDED = "electronics_included"
WEIGHING_ELECTRONICS_SEPARATE = "electronics_separate"
WEIGHING_NOT_RECORDED = "not_recorded"
WEIGHING_BASES = (WEIGHING_ELECTRONICS_INCLUDED, WEIGHING_ELECTRONICS_SEPARATE,
                  WEIGHING_NOT_RECORDED)
ELECTRONICS_ITEM_NAME = "electronics (weighed separately)"
WEIGHING_PENDING_REASON = "pending: dry-base weighing basis not recorded"
_V5_CENTRE_KEYS = ("lcg_mm_from_stern", "lcg_mm_from_midship", "tcg_mm", "kg_mm")

# Two documented dry masses within this tolerance count as the same loading.
# It absorbs floating-point sums of 1 g-step inputs, not scale-to-scale error.
MASS_MATCH_TOLERANCE_G = 0.5


def normalise_weighing_basis(value):
    """Saved or older metadata -> a known basis; missing or unknown -> not_recorded."""
    if isinstance(value, str) and value.strip() in WEIGHING_BASES:
        return value.strip()
    return WEIGHING_NOT_RECORDED


def loading_v5_weighed(base, cargo_items=(), *, weighing_basis, electronics=None):
    """loading_v5 with the dry-base weighing basis applied.

    - included: base + cargo only; any electronics entry is ignored, because the
      electronics are already in the base mass and base centre of mass;
    - separate: electronics are added as their own item (mass_g, x_mm, y_mm,
      z_mm, x from midship). A blank mass makes the total unavailable; a blank
      coordinate only blocks the matching centre;
    - not_recorded: the total mass and every centre are pending.
    Cargo items are unchanged in every case, including base-only (no items).
    """
    if weighing_basis not in WEIGHING_BASES:
        raise ValueError(f"unknown weighing_basis: {weighing_basis!r}")
    items = list(cargo_items)
    if weighing_basis == WEIGHING_ELECTRONICS_SEPARATE:
        entry = {"mass_g": None, "x_mm": None, "y_mm": None, "z_mm": None}
        entry.update(electronics or {})
        entry["name"] = ELECTRONICS_ITEM_NAME
        items.insert(0, entry)
    result = loading_v5(base, items)
    result["weighing_basis"] = weighing_basis
    if weighing_basis == WEIGHING_NOT_RECORDED:
        result["total_mass_g"] = None
        for key in _V5_CENTRE_KEYS:
            result[key] = None
        # Same keys loading_v2 uses for its own unavailable reasons.
        result["unavailable"] = {key: WEIGHING_PENDING_REASON
                                 for key in ("total_mass_g", "lcg_mm", "tcg_mm", "kg_mm")}
        result["all_outputs_available"] = False
    return result


def documented_dry_mass_g(record):
    """Dry boat mass (base, plus electronics if weighed separately) from a saved
    record; None when the weighing basis or a needed mass is unknown."""
    basis = normalise_weighing_basis(record.get("base_weighing_basis"))
    base = _optional_number(record.get("assembled_base_mass_g"), "assembled_base_mass_g")
    if basis == WEIGHING_NOT_RECORDED or base is None:
        return None
    if basis == WEIGHING_ELECTRONICS_INCLUDED:
        return base
    electronics = _optional_number(record.get("electronics_mass_g"), "electronics_mass_g")
    return None if electronics is None else base + electronics


def loading_match(first, second, mass_tolerance_g=MASS_MATCH_TOLERANCE_G):
    """Compare the documented dry boat mass and cargo of two saved runs.

    Only the dry mass and the cargo case, mass and X/Y/Z are checked. Base and
    electronics positions are not, so equal dry mass does not confirm equal
    weight distribution.

    Returns {"status": "yes" | "no" | "unknown", "differs": [...], "unknown": [...]}.
    "yes" needs every compared value known on both runs; a known difference
    gives "no"; otherwise missing metadata gives "unknown", never a match.
    The dry mass is compared as documented, so a base weighed with electronics
    matches the same boat weighed without them plus its electronics mass.
    """
    differs, unknown = [], []

    def compare(label, a, b, tolerance):
        if a is None or b is None:
            unknown.append(label)
        elif abs(a - b) > tolerance:
            differs.append(label)

    def number(record, key):
        return _optional_number(record.get(key), key)

    compare("dry boat mass", documented_dry_mass_g(first), documented_dry_mass_g(second),
            mass_tolerance_g)
    case_a, case_b = first.get("cargo_preset"), second.get("cargo_preset")
    if case_a is None or case_b is None:
        unknown.append("cargo case")
    elif case_a != case_b:
        differs.append("cargo case")
    elif case_a != "Base only":
        compare("cargo mass", number(first, "cargo_mass_g"), number(second, "cargo_mass_g"),
                mass_tolerance_g)
        for key, label in (("cargo_x_midship_mm", "cargo X"), ("cargo_y_mm", "cargo Y"),
                           ("cargo_z_mm", "cargo Z")):
            compare(label, number(first, key), number(second, key), 0.0)
    status = "no" if differs else ("unknown" if unknown else "yes")
    return {"status": status, "differs": differs, "unknown": unknown}


def v5_upright_draft(total_mass_g, density_kg_m3=1000.0):
    """Upright still-water mean draft from the V5 CAD curve. Never extrapolates.

    Other densities use volume conservation: the displaced volume m / rho is the
    same volume that would hold m * 1000 / rho grams of freshwater, which is
    then looked up in the freshwater table.
    """
    base = {"mean_draft_mm": None, "seam_freeboard_mm": None,
            "equivalent_freshwater_g": None, "density_kg_m3": None,
            "label": V5_ESTIMATE_LABEL, **V5_CAPACITY_SOURCE}
    mass = _optional_number(total_mass_g, "total_mass_g")
    rho = _optional_number(density_kg_m3, "density_kg_m3", positive=True)
    base["density_kg_m3"] = rho
    if mass is None or rho is None:
        missing = [n for n, v in (("total mass", mass), ("water density", rho)) if v is None]
        return {**base, "status": "unavailable", "reason": "missing " + " and ".join(missing)}
    if mass < 0:
        raise ValueError("total_mass_g must be nonnegative")
    if _V5_CAPACITY is None:
        return {**base, "status": "unavailable", "reason": _V5_CAPACITY_ERROR}
    equivalent = mass * V5_CAPACITY_SOURCE["reference_density_kg_m3"] / rho
    base["equivalent_freshwater_g"] = equivalent
    first_draft, first_g = V5_CAPACITY_TABLE[0]
    top_draft, top_g = V5_CAPACITY_TABLE[-1]
    if equivalent < first_g or equivalent > top_g:
        return {**base, "status": "out_of_range",
                "reason": (f"needs {equivalent:.1f} g freshwater equivalent; curve bounds are "
                           f"{first_g}–{top_g} g ({first_draft}–{top_draft} mm). "
                           "Not extrapolated.")}
    for (d0, g0), (d1, g1) in zip(V5_CAPACITY_TABLE, V5_CAPACITY_TABLE[1:]):
        if g0 <= equivalent <= g1:
            draft = d0 + (d1 - d0) * (equivalent - g0) / (g1 - g0)
            return {**base, "status": "ok", "reason": None, "mean_draft_mm": draft,
                    "seam_freeboard_mm": V5_SEAM_HEIGHT_MM - draft}
    raise AssertionError("unreachable: the table covers 0 to its top point")


def tank_reading_summary(aft_port_mm=None, aft_stbd_mm=None, fwd_port_mm=None,
                         fwd_stbd_mm=None, seam_height_mm=V5_SEAM_HEIGHT_MM):
    """Summarise four optional draft readings (mm). Blank readings stay unavailable."""
    raw = {"aft_port": aft_port_mm, "aft_stbd": aft_stbd_mm,
           "fwd_port": fwd_port_mm, "fwd_stbd": fwd_stbd_mm}
    vals = {}
    for key, value in raw.items():
        v = _optional_number(value, key)
        if v is not None and v < 0:
            raise ValueError(f"{key} must be nonnegative")
        vals[key] = v
    seam_height = _optional_number(seam_height_mm, "seam_height_mm")

    def mean(a, b):
        return None if vals[a] is None or vals[b] is None else (vals[a] + vals[b]) / 2

    aft, fwd = mean("aft_port", "aft_stbd"), mean("fwd_port", "fwd_stbd")
    port, stbd = mean("aft_port", "fwd_port"), mean("aft_stbd", "fwd_stbd")
    return {
        "mean_aft_mm": aft,
        "mean_forward_mm": fwd,
        "measured_trim_mm": measured_trim_mm(aft, fwd),        # + = stern deeper
        "transverse_difference_mm": None if port is None or stbd is None else stbd - port,
        "mean_draft_approx_mm": None if aft is None or fwd is None else (aft + fwd) / 2,
        "derived_station_freeboard_mm": {k: (None if v is None or seam_height is None
                                             else seam_height - v)
                                         for k, v in vals.items()},
        "missing_readings": [k for k, v in vals.items() if v is None],
    }


def draft_prediction_error(predicted_mm, measured_mm):
    """Signed (measured - predicted) and absolute error in mm; None if either is missing."""
    p = _optional_number(predicted_mm, "predicted_mm")
    m = _optional_number(measured_mm, "measured_mm")
    if p is None or m is None:
        return {"signed_error_mm": None, "abs_error_mm": None}
    return {"signed_error_mm": m - p, "abs_error_mm": abs(m - p)}
