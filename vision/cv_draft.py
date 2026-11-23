"""SmartTrim V5 draft-from-photo prototype (classical computer vision, OpenCV).

Reads where a horizontal edge (the waterline, or a tape edge in a dry test)
crosses each printed draft ruler in a side photo, and converts it to mm using
two known ruler ticks per ruler. Writes an annotated PNG and CSV files.

No machine learning: the crossing is the strongest colour change along a short
strip beside the ruler, checked for consistency across the strip's width.

Usage (see vision/README.md):
    python vision/cv_draft.py --image PHOTO --calibration CAL.json --run-id T03 \
        --side port [--mode waterline|tape-lower-edge] [--manual MANUAL.csv] [--out DIR]
"""
import argparse
import csv
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

MODES = ("waterline", "tape-lower-edge")

# Detector settings, fixed before the dry test and not tuned to it.
SMOOTH_SIGMA_PX = 1.0          # smoothing along the ruler before differencing
STEP_HALF_WIDTH_PX = 3         # mean of 3 px below vs 3 px above each position
MIN_CONTRAST = 10.0            # minimum colour step (CIE Lab delta E) to count as an edge
CANDIDATE_RATIO = 0.3          # candidate edges are >= 30 % of the strongest edge
AMBIGUITY_RATIO = 0.5          # waterline mode: a second edge >= 50 % is a competitor
MIN_SEPARATION_MM = 1.0        # edges closer than this are one edge
SUPPORT_TOLERANCE_MM = 0.75    # a strip column agrees if its own edge is this close
MIN_SUPPORT = 0.6              # fraction of strip columns that must agree
MAX_STRIP_SPREAD_MM = 1.0      # strips either side of a ruler must agree within this,
MAX_WATERLINE_SLOPE = 0.1      # plus this slope (mm per mm between strips, ~6 degrees)

STATION_ALIASES = {"fwd": "forward", "front": "forward", "bow": "forward",
                   "stern": "aft", "back": "aft"}

DRAFT_FIELDS = ["run_id", "image", "side", "station", "camera_draft_mm", "status", "reason",
                "mode", "crossing_x_px", "crossing_y_px", "edge_strength", "support"]
TRIM_FIELDS = ["run_id", "image", "side", "aft_draft_mm", "forward_draft_mm",
               "aft_minus_forward_mm", "status"]
COMPARISON_FIELDS = ["run_id", "image", "side", "station", "camera_draft_mm",
                     "manual_draft_mm", "camera_minus_manual_mm", "camera_status", "status"]


class CalibrationError(ValueError):
    """The calibration file is missing values or describes an impossible ruler."""


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------
def normalise_station(name):
    key = str(name).strip().lower()
    return STATION_ALIASES.get(key, key)


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise CalibrationError(f"{label} must be a finite number")
    return float(value)


def parse_ruler(entry, index):
    """Validate one ruler entry and return a ruler dict with numpy geometry."""
    label = f"rulers[{index}]"
    if not isinstance(entry, dict):
        raise CalibrationError(f"{label} must be an object")
    station = entry.get("station")
    if not isinstance(station, str) or not station.strip():
        raise CalibrationError(f"{label}.station must be a non-empty string")
    points = []
    for key in ("point_a", "point_b"):
        point = entry.get(key)
        if not isinstance(point, dict):
            raise CalibrationError(f"{label}.{key} must be an object with x, y and mm")
        points.append((_number(point.get("x"), f"{label}.{key}.x"),
                       _number(point.get("y"), f"{label}.{key}.y"),
                       _number(point.get("mm"), f"{label}.{key}.mm")))
    (xa, ya, mma), (xb, yb, mmb) = points
    if mma == mmb:
        raise CalibrationError(f"{label}: the two calibration ticks need different mm values")
    if math.hypot(xb - xa, yb - ya) < 5:
        raise CalibrationError(f"{label}: the two calibration ticks are less than 5 px apart")
    width = _number(entry.get("strip_width_px"), f"{label}.strip_width_px")
    if width < 3:
        raise CalibrationError(f"{label}.strip_width_px must be at least 3")
    raw_offsets = entry.get("strip_offset_px", 0.0)
    if not isinstance(raw_offsets, (list, tuple)):
        raw_offsets = [raw_offsets]
    if not raw_offsets:
        raise CalibrationError(f"{label}.strip_offset_px must be a number or a non-empty list")
    offsets = [_number(o, f"{label}.strip_offset_px") for o in raw_offsets]
    search = entry.get("search_mm")
    if not isinstance(search, (list, tuple)) or len(search) != 2:
        raise CalibrationError(f"{label}.search_mm must be [min_mm, max_mm]")
    search_lo = _number(search[0], f"{label}.search_mm[0]")
    search_hi = _number(search[1], f"{label}.search_mm[1]")
    if search_lo >= search_hi:
        raise CalibrationError(f"{label}.search_mm must be increasing")
    zero_offset = _number(entry.get("zero_offset_mm", 0.0), f"{label}.zero_offset_mm")

    origin = np.array([xa, ya])
    per_mm = (np.array([xb, yb]) - origin) / (mmb - mma)      # px moved per +1 mm
    px_per_mm = float(np.linalg.norm(per_mm))
    normal = np.array([-per_mm[1], per_mm[0]]) / px_per_mm     # unit, across the ruler
    return {"station": normalise_station(station), "station_label": station.strip(),
            "origin": origin, "origin_mm": mma, "per_mm": per_mm, "px_per_mm": px_per_mm,
            "normal": normal, "strip_offsets_px": offsets, "strip_width_px": width,
            "search_mm": (search_lo, search_hi),
            "calibrated_mm": (min(mma, mmb), max(mma, mmb)),
            "points": [(xa, ya, mma), (xb, yb, mmb)], "zero_offset_mm": zero_offset}


def load_calibration(path_or_dict):
    data = path_or_dict
    if not isinstance(data, dict):
        data = json.loads(Path(path_or_dict).read_text(encoding="utf-8"))
    rulers = data.get("rulers") if isinstance(data, dict) else None
    if not isinstance(rulers, list) or not rulers:
        raise CalibrationError("calibration must contain a non-empty 'rulers' list")
    parsed = [parse_ruler(entry, i) for i, entry in enumerate(rulers)]
    stations = [r["station"] for r in parsed]
    if len(set(stations)) != len(stations):
        raise CalibrationError(f"duplicate station names: {stations}")
    return parsed


def mm_to_px(ruler, mm, across_px=0.0):
    """Image point for a ruler reading in mm, shifted across the ruler by across_px."""
    return ruler["origin"] + (mm - ruler["origin_mm"]) * ruler["per_mm"] + across_px * ruler["normal"]


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
def _step_profile(values, half):
    """Colour step at each sample: mean of the next `half` minus the previous `half`.

    values: (columns, samples, 3) Lab. Returns (columns, samples) delta-E magnitude.
    """
    n = values.shape[1]
    magnitude = np.zeros(values.shape[:2])
    if n < 2 * half + 1:
        return magnitude
    # csum[:, j] = sum of samples [0, j); below = samples [i-half, i), above = (i, i+half]
    csum = np.concatenate([np.zeros_like(values[:, :1]), np.cumsum(values, axis=1)], axis=1)
    idx = np.arange(half, n - half)
    below = (csum[:, idx] - csum[:, idx - half]) / half
    above = (csum[:, idx + 1 + half] - csum[:, idx + 1]) / half
    magnitude[:, idx] = np.linalg.norm(above - below, axis=2)
    return magnitude


def _peaks(profile, min_value, min_separation):
    """Local maxima >= min_value, strongest first, with non-maximum suppression."""
    candidates = [i for i in range(1, len(profile) - 1)
                  if profile[i] >= min_value and profile[i] >= profile[i - 1]
                  and profile[i] >= profile[i + 1]]
    candidates.sort(key=lambda i: profile[i], reverse=True)
    kept = []
    for i in candidates:
        if all(abs(i - k) >= min_separation for k in kept):
            kept.append(i)
    return kept


def _subsample(profile, i):
    """Parabolic sub-sample position of a peak at index i."""
    if 0 < i < len(profile) - 1:
        left, centre, right = profile[i - 1], profile[i], profile[i + 1]
        denominator = left - 2 * centre + right
        if denominator < 0:
            return i + 0.5 * (left - right) / denominator
    return float(i)


def _measure_strip(lab_image, ruler, offset_px, mode):
    """Find the edge crossing in one strip beside the ruler (no range check here)."""
    height, width = lab_image.shape[:2]
    lo, hi = ruler["search_mm"]
    step_mm = 1.0 / ruler["px_per_mm"]                       # one sample per pixel
    sample_mm = np.arange(lo, hi + step_mm / 2, step_mm)
    half_width = ruler["strip_width_px"] / 2
    across = np.arange(-half_width, half_width + 0.5, 1.0) + offset_px
    points = (ruler["origin"][None, None, :]
              + (sample_mm[None, :, None] - ruler["origin_mm"]) * ruler["per_mm"][None, None, :]
              + across[:, None, None] * ruler["normal"][None, None, :])
    map_x = points[..., 0].astype(np.float32)
    map_y = points[..., 1].astype(np.float32)
    result = {"offset_px": offset_px, "crossing_mm": None, "crossing_px": None,
              "edge_strength": None, "support": None, "candidates_mm": [],
              "corners_px": [mm_to_px(ruler, m, a) for m, a in
                             ((lo, across[0]), (hi, across[0]), (hi, across[-1]), (lo, across[-1]))]}

    if (map_x.min() < 0 or map_y.min() < 0 or map_x.max() > width - 1
            or map_y.max() > height - 1):
        return {**result, "status": "not_visible",
                "reason": "the measurement strip extends outside the image"}

    strip = cv2.remap(lab_image, map_x, map_y, interpolation=cv2.INTER_LINEAR)
    strip = cv2.GaussianBlur(strip, (0, 0), sigmaX=SMOOTH_SIGMA_PX, sigmaY=0.01)
    half = STEP_HALF_WIDTH_PX
    per_column = _step_profile(strip, half)
    profile = _step_profile(np.median(strip, axis=0, keepdims=True), half)[0]

    strongest = float(profile.max())
    if strongest < MIN_CONTRAST:
        return {**result, "status": "no_edge",
                "reason": f"no colour step of at least {MIN_CONTRAST:g} (strongest {strongest:.1f})"}

    separation = MIN_SEPARATION_MM * ruler["px_per_mm"]
    candidates = _peaks(profile, max(MIN_CONTRAST, CANDIDATE_RATIO * strongest), separation)
    to_mm = lambda i: lo + i * step_mm  # noqa: E731
    result["candidates_mm"] = sorted(round(to_mm(_subsample(profile, i)), 2) for i in candidates)

    if mode == "tape-lower-edge":
        chosen = min(candidates)                      # lowest mm = lower edge of the tape
    else:
        chosen = candidates[0]                        # strongest edge
        competitors = [i for i in candidates[1:] if profile[i] >= AMBIGUITY_RATIO * profile[chosen]]
        if competitors:
            other = competitors[0]
            return {**result, "status": "ambiguous",
                    "reason": (f"competing edges at {to_mm(_subsample(profile, chosen)):.1f} mm and "
                               f"{to_mm(_subsample(profile, other)):.1f} mm "
                               f"(strength ratio {profile[other] / profile[chosen]:.2f})")}

    crossing_mm = to_mm(_subsample(profile, chosen))
    tolerance = max(1, int(round(SUPPORT_TOLERANCE_MM * ruler["px_per_mm"])))
    window = slice(max(0, chosen - tolerance), chosen + tolerance + 1)
    support = float((per_column[:, window].max(axis=1) >= 0.5 * profile[chosen]).mean())
    result.update(crossing_mm=crossing_mm, crossing_px=mm_to_px(ruler, crossing_mm, offset_px),
                  edge_strength=float(profile[chosen]), support=support)
    if support < MIN_SUPPORT:
        return {**result, "status": "weak_support",
                "reason": f"edge continuous across only {support:.0%} of the strip"}
    return {**result, "status": "ok", "reason": ""}


def measure_ruler(lab_image, ruler, mode="waterline"):
    """Reading for one ruler. Returns a result dict; draft_mm is None unless status is ok.

    Each strip is measured separately. With strips on both sides of the ruler the
    mean cancels a sloping (trimmed) waterline; all strips must succeed and agree.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    strips = [_measure_strip(lab_image, ruler, offset, mode) for offset in ruler["strip_offsets_px"]]
    result = {"station": ruler["station"], "station_label": ruler["station_label"], "mode": mode,
              "draft_mm": None, "crossing_mm": None, "crossing_px": None, "strips": strips,
              "edge_strength": None, "support": None}
    failed = [s for s in strips if s["status"] != "ok"]
    if failed:
        first = failed[0]
        where = f"strip at {first['offset_px']:+g} px: " if len(strips) > 1 else ""
        return {**result, "status": first["status"], "reason": where + first["reason"]}
    crossings = [s["crossing_mm"] for s in strips]
    spread = max(crossings) - min(crossings)
    crossing_mm = sum(crossings) / len(crossings)
    mean_offset = sum(ruler["strip_offsets_px"]) / len(strips)
    result.update(crossing_mm=crossing_mm, crossing_px=mm_to_px(ruler, crossing_mm, mean_offset),
                  edge_strength=min(s["edge_strength"] for s in strips),
                  support=min(s["support"] for s in strips))
    offsets = ruler["strip_offsets_px"]
    separation_mm = (max(offsets) - min(offsets)) / ruler["px_per_mm"]
    allowed = MAX_STRIP_SPREAD_MM + MAX_WATERLINE_SLOPE * separation_mm
    if spread > allowed:
        return {**result, "status": "inconsistent",
                "reason": (f"strips disagree by {spread:.1f} mm, more than {allowed:.1f} mm "
                           f"({', '.join(f'{c:.1f}' for c in crossings)} mm)")}
    cal_lo, cal_hi = ruler["calibrated_mm"]
    if not cal_lo <= crossing_mm <= cal_hi:
        return {**result, "status": "out_of_range",
                "reason": (f"crossing at {crossing_mm:.1f} mm is outside the calibrated "
                           f"{cal_lo:g}-{cal_hi:g} mm ticks")}
    return {**result, "status": "ok", "reason": "",
            "draft_mm": crossing_mm + ruler["zero_offset_mm"]}


def to_lab(image_bgr):
    return cv2.cvtColor(image_bgr.astype(np.float32) / 255.0, cv2.COLOR_BGR2Lab)


def measure_image(image_bgr, rulers, mode="waterline"):
    lab = to_lab(image_bgr)
    return [measure_ruler(lab, ruler, mode) for ruler in rulers]


def side_trim(results):
    """Aft minus forward on one side, only when both readings are available."""
    by_station = {r["station"]: r for r in results}
    aft, forward = by_station.get("aft"), by_station.get("forward")
    if aft is None or forward is None:
        return {"aft_draft_mm": None, "forward_draft_mm": None, "aft_minus_forward_mm": None,
                "status": "not applicable: needs 'aft' and 'forward' stations"}
    aft_mm, forward_mm = aft["draft_mm"], forward["draft_mm"]
    if aft_mm is None or forward_mm is None:
        blank = [name for name, value in (("aft", aft_mm), ("forward", forward_mm)) if value is None]
        return {"aft_draft_mm": aft_mm, "forward_draft_mm": forward_mm,
                "aft_minus_forward_mm": None,
                "status": "unavailable: " + " and ".join(blank) + " reading blank"}
    return {"aft_draft_mm": aft_mm, "forward_draft_mm": forward_mm,
            "aft_minus_forward_mm": aft_mm - forward_mm, "status": "ok"}


# ---------------------------------------------------------------------------
# Manual readings
# ---------------------------------------------------------------------------
def load_manual(path):
    """Manual readings keyed by (run_id, side, station). Blank values stay None."""
    readings = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            key = (str(row.get("run_id", "")).strip(), str(row.get("side", "")).strip().lower(),
                   normalise_station(row.get("station", "")))
            text = str(row.get("manual_draft_mm", "") or "").strip()
            try:
                value = float(text) if text else None
            except ValueError:
                value = None
            readings[key] = value if value is None or math.isfinite(value) else None
    return readings


def compare_manual(run_id, image_name, side, results, manual):
    rows = []
    for r in results:
        key = (run_id, side.lower(), r["station"])
        manual_mm = manual.get(key)
        camera_mm = r["draft_mm"]
        if key not in manual:
            status = "no manual reading for this station"
        elif manual_mm is None:
            status = "manual reading blank"
        elif camera_mm is None:
            status = f"camera reading blank ({r['status']})"
        else:
            status = "ok"
        difference = camera_mm - manual_mm if status == "ok" else None
        rows.append({"run_id": run_id, "image": image_name, "side": side,
                     "station": r["station_label"], "camera_draft_mm": _fmt(camera_mm),
                     "manual_draft_mm": _fmt(manual_mm), "camera_minus_manual_mm": _fmt(difference),
                     "camera_status": r["status"], "status": status})
    return rows


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def _fmt(value, digits=2):
    return "" if value is None else f"{value:.{digits}f}"


def annotate(image_bgr, rulers, results):
    out = image_bgr.copy()
    scale = max(out.shape[:2]) / 1000.0
    thick = max(1, int(round(2 * scale)))
    font = 0.5 * scale
    def point(p):
        return tuple(int(v) for v in np.round(p))

    for ruler, r in zip(rulers, results):
        ok = r["status"] == "ok"
        colour = (0, 170, 0) if ok else (0, 0, 230)
        all_corners = []
        for strip in r["strips"]:
            corners = np.array(strip["corners_px"], dtype=np.float32).round().astype(np.int32)
            all_corners.append(corners)
            cv2.polylines(out, [corners], True, (0, 200, 255), thick)
            if strip["crossing_px"] is not None:          # where this strip found its edge
                half = ruler["normal"] * ruler["strip_width_px"] / 2
                strip_colour = (0, 170, 0) if strip["status"] == "ok" else (0, 0, 230)
                cv2.line(out, point(strip["crossing_px"] - half), point(strip["crossing_px"] + half),
                         strip_colour, thick, cv2.LINE_AA)
        for x, y, mm in ruler["points"]:
            cv2.circle(out, point((x, y)), 3 * thick, (255, 200, 0), thick)
            cv2.putText(out, f"{mm:g} mm", point((x + 4 * thick, y + 4 * thick)),
                        cv2.FONT_HERSHEY_SIMPLEX, font, (255, 200, 0), thick, cv2.LINE_AA)
        if r["crossing_px"] is not None:                  # combined reading on the ruler line
            cv2.drawMarker(out, point(r["crossing_px"]), colour, cv2.MARKER_CROSS,
                           6 * thick, thick, cv2.LINE_AA)
        text = (f"{r['station_label']}: {r['draft_mm']:.1f} mm" if ok
                else f"{r['station_label']}: blank ({r['status']})")
        anchor = np.vstack(all_corners).min(axis=0)
        cv2.putText(out, text, (int(anchor[0]), max(int(anchor[1]) - 6 * thick, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, font, colour, thick, cv2.LINE_AA)
    return out


def _write_csv(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(image_path, calibration_path, run_id, side, mode="waterline", manual_path=None,
        out_dir=None):
    """Measure one photo and write its outputs. Returns a summary dict."""
    image_path = Path(image_path)
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"could not read image: {image_path}")
    rulers = load_calibration(calibration_path)
    results = measure_image(image, rulers, mode)
    out_dir = Path(out_dir) if out_dir else Path(__file__).resolve().parent / "output" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{run_id}_{side}_{image_path.stem}"

    draft_rows = [{"run_id": run_id, "image": image_path.name, "side": side,
                   "station": r["station_label"], "camera_draft_mm": _fmt(r["draft_mm"]),
                   "status": r["status"], "reason": r["reason"], "mode": mode,
                   "crossing_x_px": _fmt(None if r["crossing_px"] is None else r["crossing_px"][0], 1),
                   "crossing_y_px": _fmt(None if r["crossing_px"] is None else r["crossing_px"][1], 1),
                   "edge_strength": _fmt(r["edge_strength"], 1), "support": _fmt(r["support"])}
                  for r in results]
    trim = side_trim(results)
    trim_row = {"run_id": run_id, "image": image_path.name, "side": side,
                "aft_draft_mm": _fmt(trim["aft_draft_mm"]),
                "forward_draft_mm": _fmt(trim["forward_draft_mm"]),
                "aft_minus_forward_mm": _fmt(trim["aft_minus_forward_mm"]), "status": trim["status"]}
    files = {"annotated": out_dir / f"{stem}_annotated.png",
             "drafts": out_dir / f"{stem}_camera_drafts.csv",
             "trim": out_dir / f"{stem}_trim.csv"}
    cv2.imwrite(str(files["annotated"]), annotate(image, rulers, results))
    _write_csv(files["drafts"], DRAFT_FIELDS, draft_rows)
    _write_csv(files["trim"], TRIM_FIELDS, [trim_row])
    comparison = None
    if manual_path:
        comparison = compare_manual(run_id, image_path.name, side, results, load_manual(manual_path))
        files["comparison"] = out_dir / f"{stem}_comparison.csv"
        _write_csv(files["comparison"], COMPARISON_FIELDS, comparison)
    return {"results": results, "drafts": draft_rows, "trim": trim_row,
            "comparison": comparison, "files": files}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--image", required=True, help="side photo (JPG/PNG)")
    parser.add_argument("--calibration", required=True, help="calibration JSON (see README)")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--side", required=True, help="port, starboard, or bench for a dry test")
    parser.add_argument("--mode", choices=MODES, default="waterline",
                        help="waterline: strongest edge, blank if competing edges; "
                             "tape-lower-edge: lowest edge (dry tape test)")
    parser.add_argument("--manual", help="manual readings CSV to compare against")
    parser.add_argument("--out", help="output folder (default vision/output/<run-id>)")
    args = parser.parse_args(argv)
    try:
        summary = run(args.image, args.calibration, args.run_id, args.side, args.mode,
                      args.manual, args.out)
    except (CalibrationError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for row in summary["drafts"]:
        value = row["camera_draft_mm"] or "blank"
        detail = f" — {row['reason']}" if row["reason"] else ""
        print(f"{row['side']} {row['station']}: {value} mm [{row['status']}]{detail}")
    print(f"aft minus forward: {summary['trim']['aft_minus_forward_mm'] or 'blank'} "
          f"[{summary['trim']['status']}]")
    for row in summary["comparison"] or []:
        print(f"compare {row['station']}: camera {row['camera_draft_mm'] or 'blank'} / manual "
              f"{row['manual_draft_mm'] or 'blank'} / difference "
              f"{row['camera_minus_manual_mm'] or 'blank'} mm [{row['status']}]")
    for name, path in summary["files"].items():
        print(f"wrote {name}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
