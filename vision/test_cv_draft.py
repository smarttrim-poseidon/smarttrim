"""Synthetic tests for the draft-from-photo prototype. No real photos are needed."""
import csv
import json

import pytest

cv2 = pytest.importorskip("cv2", reason="OpenCV is required for the vision prototype")
import numpy as np  # noqa: E402

import cv_draft  # noqa: E402

PX_PER_MM = 8.0
ZERO_Y = 600            # image row of the 0 mm keel datum (pixel centres at integer rows)
AFT_X, FWD_X = 200, 700  # ruler left edges; aft on the left in this side photo
RULER_WIDTH = 40
AFT_AXIS, FWD_AXIS = AFT_X + RULER_WIDTH / 2, FWD_X + RULER_WIDTH / 2   # ruler centre lines
HULL = (200, 200, 200)  # BGR light grey
WATER = (120, 90, 40)   # BGR dark blue
TAPE = (40, 170, 210)   # BGR yellow


def y_at(mm):
    return ZERO_Y - mm * PX_PER_MM


def paint_between(img, upper_y, colour, lower_y=None):
    """Paint each column from image row upper_y[x] down to lower_y[x] (default: bottom).

    Exact pixel coverage: row r covers r-0.5..r+0.5, matching OpenCV's pixel-centre
    convention, so the rendered edges sit exactly at upper_y and lower_y.
    """
    rows = np.arange(img.shape[0])[:, None] + 0.0
    cover = np.clip(rows + 0.5 - upper_y[None, :], 0.0, 1.0)            # below upper edge
    if lower_y is not None:
        cover = np.minimum(cover, np.clip(lower_y[None, :] - (rows - 0.5), 0.0, 1.0))
    blended = img * (1 - cover[..., None]) + np.array(colour, float) * cover[..., None]
    img[:] = np.round(blended).astype(np.uint8)


def draw_ruler(img, x):
    cv2.rectangle(img, (x, int(y_at(65))), (x + 40, ZERO_Y), (255, 255, 255), -1)
    for mm in range(0, 66):
        length = 24 if mm % 10 == 0 else 16 if mm % 5 == 0 else 10
        y = int(round(y_at(mm)))
        cv2.line(img, (x, y), (x + length, y), (0, 0, 0), 1)


def side_photo(aft_mm=30.0, fwd_mm=25.0, band_mm=None, band_colour=WATER, water=True):
    """Hull with two rulers and a straight waterline through the given readings.

    aft_mm and fwd_mm are the water levels on the two ruler centre lines.
    band_mm adds a 4 mm horizontal band (a reflection, or a tape strip) starting there.
    """
    img = np.full((700, 900, 3), HULL, np.uint8)
    draw_ruler(img, AFT_X)
    draw_ruler(img, FWD_X)
    columns = np.arange(img.shape[1]) + 0.0
    if band_mm is not None:
        paint_between(img, np.full_like(columns, y_at(band_mm + 4)), band_colour,
                      lower_y=np.full_like(columns, y_at(band_mm)))
    if water:
        slope = (fwd_mm - aft_mm) / (FWD_AXIS - AFT_AXIS)   # mm per px along the hull
        level_mm = aft_mm + slope * (columns - AFT_AXIS)
        paint_between(img, y_at(level_mm), WATER)
    return img


def calibration(search=(2.0, 62.0), ticks=(10.0, 50.0), offset=(-40.0, 40.0)):
    """Ticks picked on the ruler centre line (x + 20); strips 40 px either side clear the ruler."""
    rulers = []
    for station, x in (("aft", AFT_X), ("forward", FWD_X)):
        rulers.append({"station": station,
                       "point_a": {"x": x + 20.0, "y": y_at(ticks[0]), "mm": ticks[0]},
                       "point_b": {"x": x + 20.0, "y": y_at(ticks[1]), "mm": ticks[1]},
                       "strip_offset_px": offset, "strip_width_px": 30,
                       "search_mm": list(search), "zero_offset_mm": 0.0})
    return {"rulers": rulers}


def measure(img, mode="waterline", cal=None):
    rulers = cv_draft.load_calibration(cal or calibration())
    return {r["station"]: r for r in cv_draft.measure_image(img, rulers, mode)}


def test_synthetic_25_forward_30_aft_gives_plus_5_mm():
    results = measure(side_photo(aft_mm=30.0, fwd_mm=25.0))
    assert results["aft"]["status"] == "ok" and results["forward"]["status"] == "ok"
    assert results["aft"]["draft_mm"] == pytest.approx(30.0, abs=0.1)
    assert results["forward"]["draft_mm"] == pytest.approx(25.0, abs=0.1)
    trim = cv_draft.side_trim(list(results.values()))
    assert trim["status"] == "ok"
    assert trim["aft_minus_forward_mm"] == pytest.approx(5.0, abs=0.1)


def test_competing_edge_leaves_reading_blank_in_waterline_mode():
    # A dark reflection band at 40-44 mm competes with the real waterline.
    results = measure(side_photo(band_mm=40.0))
    aft = results["aft"]
    assert aft["status"] == "ambiguous" and aft["draft_mm"] is None
    assert "competing edges" in aft["reason"]
    trim = cv_draft.side_trim(list(results.values()))
    assert trim["aft_minus_forward_mm"] is None and trim["status"].startswith("unavailable")


def test_crossing_outside_calibrated_ticks_is_blank():
    # Waterline at 55 mm aft, inside the search window but above the 10-50 mm ticks.
    results = measure(side_photo(aft_mm=55.0, fwd_mm=45.0))
    assert results["aft"]["status"] == "out_of_range" and results["aft"]["draft_mm"] is None
    assert "outside the calibrated 10-50 mm" in results["aft"]["reason"]
    assert results["forward"]["status"] == "ok"
    assert results["forward"]["draft_mm"] == pytest.approx(45.0, abs=0.25)
    assert cv_draft.side_trim(list(results.values()))["aft_minus_forward_mm"] is None


def test_no_edge_and_strip_outside_image():
    no_water = measure(side_photo(water=False))
    assert no_water["aft"]["status"] == "no_edge" and no_water["aft"]["draft_mm"] is None
    off_image = measure(side_photo(), cal=calibration(offset=900.0))
    assert off_image["aft"]["status"] == "not_visible"


def test_one_sided_strip_reads_the_waterline_beside_the_ruler():
    # A single strip 60 px from the ruler on a trimmed waterline reads where the strip is.
    # Both-side strips cancel this; one-sided strips are for level edges (dry tape test).
    results = measure(side_photo(aft_mm=30.0, fwd_mm=25.0), cal=calibration(offset=60.0))
    slope_mm_per_px = (25.0 - 30.0) / (FWD_AXIS - AFT_AXIS)
    assert results["aft"]["draft_mm"] == pytest.approx(30.0 + 60 * slope_mm_per_px, abs=0.25)
    trim = cv_draft.side_trim(list(results.values()))
    assert trim["aft_minus_forward_mm"] == pytest.approx(5.0, abs=0.3)   # equal shift cancels


def test_strips_that_disagree_leave_the_reading_blank():
    # Water locally raised to 34 mm on one side of the aft ruler only (a splash):
    # one strip reads ~30 mm, the other ~34 mm, more than the 2 mm allowed here.
    img = side_photo(aft_mm=30.0, fwd_mm=25.0)
    cv2.rectangle(img, (AFT_X + 45, int(round(y_at(34)))), (AFT_X + 75, int(y_at(28))), WATER, -1)
    aft = measure(img)["aft"]
    assert aft["draft_mm"] is None and aft["status"] == "inconsistent"
    assert "strips disagree" in aft["reason"]


def test_tape_lower_edge_mode_picks_the_lower_edge():
    img = side_photo(water=False, band_mm=20.0, band_colour=TAPE)   # tape 20-24 mm
    tape = measure(img, mode="tape-lower-edge")
    assert tape["aft"]["status"] == "ok"
    assert tape["aft"]["draft_mm"] == pytest.approx(20.0, abs=0.25)
    # The same image in waterline mode has two competing edges.
    assert measure(img, mode="waterline")["aft"]["status"] == "ambiguous"


def test_manual_comparison_per_station(tmp_path):
    results = measure(side_photo(aft_mm=30.0, fwd_mm=25.0))
    manual = tmp_path / "manual.csv"
    manual.write_text("run_id,image,side,station,station_x_from_stern_mm,manual_draft_mm,"
                      "observed_at,notes\nT01,x.jpg,port,aft,25,29.5,,\n"
                      "T01,x.jpg,port,fwd,175,,,unreadable\n", encoding="utf-8")
    rows = {r["station"]: r for r in cv_draft.compare_manual(
        "T01", "x.jpg", "port", list(results.values()), cv_draft.load_manual(manual))}
    assert float(rows["aft"]["camera_minus_manual_mm"]) == pytest.approx(0.5, abs=0.25)
    assert rows["forward"]["camera_minus_manual_mm"] == ""
    assert rows["forward"]["status"] == "manual reading blank"


@pytest.mark.parametrize("change", [
    {"point_b": {"x": 205.0, "y": 520.0, "mm": 10.0}},           # same mm as point_a
    {"strip_width_px": 1},
    {"search_mm": [40.0, 20.0]},
    {"point_a": {"x": "205", "y": 520.0, "mm": 10.0}},
])
def test_invalid_calibration_is_rejected(change):
    cal = calibration()
    cal["rulers"][0].update(change)
    with pytest.raises(cv_draft.CalibrationError):
        cv_draft.load_calibration(cal)


def test_cli_writes_annotated_png_and_csvs(tmp_path):
    image = tmp_path / "T02_port_01.png"
    cv2.imwrite(str(image), side_photo(aft_mm=30.0, fwd_mm=25.0))
    cal = tmp_path / "cal.json"
    cal.write_text(json.dumps(calibration()), encoding="utf-8")
    out = tmp_path / "out"
    code = cv_draft.main(["--image", str(image), "--calibration", str(cal), "--run-id", "T02",
                          "--side", "port", "--out", str(out)])
    assert code == 0
    annotated = cv2.imread(str(out / "T02_port_T02_port_01_annotated.png"))
    assert annotated is not None and annotated.shape == (700, 900, 3)
    with open(out / "T02_port_T02_port_01_camera_drafts.csv", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [r["station"] for r in rows] == ["aft", "forward"]
    assert {"run_id", "side", "station", "camera_draft_mm", "status"} <= set(rows[0])
    assert all(r["run_id"] == "T02" and r["side"] == "port" and r["status"] == "ok" for r in rows)
    with open(out / "T02_port_T02_port_01_trim.csv", newline="") as handle:
        trim = next(csv.DictReader(handle))
    assert float(trim["aft_minus_forward_mm"]) == pytest.approx(5.0, abs=0.3)
    assert cv_draft.main(["--image", str(tmp_path / "missing.jpg"), "--calibration", str(cal),
                          "--run-id", "T02", "--side", "port", "--out", str(out)]) == 2
