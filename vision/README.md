# SmartTrim V5 computer vision (classical OpenCV)

Two standalone tools. Neither uses machine learning.

- **`aruco_check.py`** detects one ArUco marker (default `DICT_4X4_50`, ID 0, 40 mm) in a video, frame by frame. It writes a per-frame CSV of detection status and corner pixels, plus annotated frames. It made the detection CSVs used by the browser demo. It estimates no pose, because that needs a calibrated camera. Its detection rate is not a measure of accuracy or vessel stability.

  ```bash
  python vision/aruco_check.py --video clip.mp4 --time 6.0 [--scan] [--dictionary DICT_4X4_50] [--marker-id 0] [--marker-mm 40] [--out FOLDER]
  ```

- **`cv_draft.py`** is the draft-from-photo prototype described below.

## Draft-from-photo prototype

This is a standalone prototype that uses classical computer vision (OpenCV), not machine learning. It reads where the waterline crosses each printed draft ruler in a side photo. It gives the reading in mm next to the manual readings, and writes an annotated PNG and CSV files. It does not change the Streamlit dashboard, the calculations or the Arduino sketch.

**Status:** tested on synthetic images and one dry bench photo. **It has not been validated on real waterline photos.** The manual readings remain the reference for tank tests.

## Requirements

Python 3.10+ with numpy and OpenCV 4.7 or newer (for the `ArucoDetector` API). From the repository root: `pip install -r requirements-vision.txt`. Developed with OpenCV 4.11. The tests skip themselves if OpenCV is missing.

## Run

```bash
python vision/cv_draft.py --image PHOTO.jpg --calibration CAL.json \
    --run-id T03 --side port [--mode waterline] [--manual T03_manual.csv] [--out FOLDER]
```

Outputs go to `vision/output/<run-id>/` by default. Git ignores that folder, along with all photos and videos under `vision/`.

| File | Contents |
|---|---|
| `<run>_<side>_<image>_annotated.png` | Measurement strips (orange), calibration ticks (blue), each strip's edge, and the reading or the reason it is blank |
| `..._camera_drafts.csv` | `run_id, image, side, station, camera_draft_mm, status, reason`, plus pixel position, edge strength and support |
| `..._trim.csv` | Aft minus forward for that side. It is filled only when both the `aft` and `forward` readings are `ok`. |
| `..._comparison.csv` | Only with `--manual`. Camera minus manual for each station, blank when either value is missing. |

## Calibration file

There is one entry per ruler, with pixel coordinates read from the photo. For example, open it in Paint, zoom in, and read the x/y shown in the status bar.

```json
{"rulers": [{"station": "aft",
             "point_a": {"x": 410, "y": 880, "mm": 10},
             "point_b": {"x": 412, "y": 560, "mm": 40},
             "strip_offset_px": [-45, 45], "strip_width_px": 30,
             "search_mm": [5, 60], "zero_offset_mm": 0}]}
```

- **`point_a` / `point_b`:** two known ticks on the ruler's centre line. The reading is linear between them, so the ruler must face the camera.
- **`strip_offset_px`:** where to look, across the ruler. Positive is to the right when the numbers increase upward in the photo.
  - For the waterline, use one strip on each side, e.g. `[-45, 45]`, clear of ticks and numbers. Their average cancels the slope of a trimmed waterline.
  - A single strip reads the water where that strip is, which is off by slope × distance. Use it only for a level edge, such as the dry tape test.
- **`search_mm`:** the range searched. It may extend past the ticks so that an out-of-range crossing is reported rather than missed.
- **`zero_offset_mm`:** added to the reading. Use it if the ruler's zero is not at the keel datum.
- **Stations:** name them `aft` and `forward` (`fwd` is accepted) to get the trim.

## Modes and statuses

- **`waterline` (default):** uses the strongest colour change in each strip. If a second edge is at least half as strong (a reflection, for example), the reading is left blank.
- **`tape-lower-edge`:** uses the lowest candidate edge. It is for dry tests, where a piece of tape stands in for the waterline.

The detector settings at the top of `cv_draft.py` were fixed before the dry test and were not tuned to it.

| Status | Reading | Meaning |
|---|---|---|
| `ok` | value | One clear edge, continuous across the strip and inside the calibrated ticks |
| `ambiguous` | blank | Competing edges (waterline mode) |
| `out_of_range` | blank | The crossing is outside the two calibration ticks |
| `inconsistent` | blank | The strips on either side of the ruler disagree by more than 1 mm + 0.1 × their spacing |
| `weak_support` | blank | The edge covers less than 60 % of the strip width |
| `no_edge` | blank | No colour change of at least 10 (Lab ΔE) |
| `not_visible` | blank | A strip extends outside the photo |

## Manual readings

These use the same columns as the team's capture sheet: `run_id,image,side,station,station_x_from_stern_mm,manual_draft_mm,observed_at,notes`. Rows are matched by `run_id`, `side` and `station`. Record the manual readings before looking at the camera results.

## Results so far

**Synthetic images** (`vision/test_cv_draft.py`; 13 tests, run with the full suite):

- A slanted waterline at 30 mm aft and 25 mm forward reads 30.0 and 25.0 mm, giving aft minus forward = **+5.0 mm** (within 0.1 mm). Hard edges are recovered with 0.00 px error.
- A reflection band reads as `ambiguous`, and the aft-minus-forward value stays blank.
- A waterline at 55 mm with 10–50 mm ticks reads as `out_of_range`, and the value stays blank.
- A locally raised waterline on one side of a ruler reads as `inconsistent`.

**Dry bench photo** (`photos/ruler_tape.jpg`, one cm ruler, target = lower tape edge):

| | Value |
|---|---|
| By-eye reference (recorded first, in `examples/ruler_tape_reference.csv`) | 24.5 mm: lower physical edge of the tape (bottom of its white lip). The yellow colour ends at about 25.3 mm by eye. |
| Camera, `tape-lower-edge` mode | **25.36 mm**, `ok` (edge strength 30.4, continuous across 100 % of the strip) |
| Camera minus by-eye | **+0.86 mm** |

The detector found exactly one edge, where the yellow tape changes to white. The white lip's lower boundary has too little contrast (below the threshold of 10) to become a candidate. So the camera measured the colour edge, which agrees with the by-eye colour edge to about 0.1 mm, not the physical edge. On water, the reading will likewise be the strongest visible colour change. A meniscus, a wet rim or a translucent hull could separate that from the line a person reads. This is exactly what the tank photos must check.

**Real waterline photos:** pending. Report synthetic, dry and wet results separately.

The dry-test photo is not in this repository, so that result cannot be re-run from a clone. Its calibration and by-eye reference are in `vision/examples/`. The synthetic-image tests (`pytest vision`) run without any photo. With a photo and a calibration file of your own, the command is:

```bash
python vision/cv_draft.py --image ruler_tape.jpg \
    --calibration vision/examples/ruler_tape_calibration.json --run-id DRY_TAPE_01 \
    --side bench --mode tape-lower-edge --manual vision/examples/ruler_tape_reference.csv
```

## Photos needed from the tank

- For each run, one photo per side with both rulers in the frame. Keep the phone level with the waterline, square to the hull and steady, in diffuse light.
- One dry photo per side showing the zero marks.
- 2–3 extra frames of the same steady state.
- The four manual readings, taken before anyone looks at camera results.
- Keep the original files. Use the Run ID in the file names, e.g. `T03_port_01.jpg`.

## Limits

- The ruler must face the camera.
- Readings are linear between the two calibration ticks only.
- Refraction and the meniscus are not modelled.
- One photo gives one side. Comparing all four stations needs port and starboard photos of the same steady state.
