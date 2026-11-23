# SmartTrim V5 · Test Replay (browser demo)

A static web page with two tabs, separate from the Streamlit dashboard. It runs offline. Three.js r160 is vendored in `vendor/three/` with its MIT licence and checksums. The prepared recordings, detection CSVs and V5 preview mesh are committed in `media/`, so the page works straight from a clone or on GitHub Pages.

| Tab | Shows | Data |
|---|---|---|
| **ArUco Detection Review** | The video with the outline and numbered corners of marker ID 0. They are drawn only on frames where the detection CSV records a detection. Each frame shows a status: *Marker ID 0 detected*, *Marker not detected*, or *No detection data for this frame*. Below the timeline, **Detection statistics** summarise the selected recording and compare the detection rate of every recording. | Real videos (two bench recordings and one water-tank recording), each with its detection CSV from [`vision/aruco_check.py`](../vision/aruco_check.py) |
| **3D Motion Replay** | The V5 model tilting with recorded roll and pitch. It has its own timeline and a roll/pitch chart; gaps are shaded and never joined. | Any SmartTrim sensor CSV. A clearly labelled **simulated** sample loads by default. |

The two timelines are independent. A shared timeline is turned on only for a video and a sensor CSV from the same run with a verified time offset. None exists yet, and the page says so.

## Open the demo

**Online:** the GitHub Pages deployment of this folder (see the repository README for the link).

**Locally** (Python 3.10+, no packages needed), from the repository root:

```bash
python demo/serve.py            # then open http://127.0.0.1:8765/
python demo/serve.py --port 8766   # if 8765 is busy
```

The page needs an HTTP server, because browsers block ES modules and file loading from `file://`. Any static server works; `serve.py` only adds correct content types (some Windows set-ups serve `.js` as `text/plain`) and binds to 127.0.0.1. Use a current Chrome, Edge or Firefox. Useful URLs: `?present` (presentation mode), `?view=showcase` (1920×1080 layout), `?clip=water_controlled` (open a recording first).

If `media/` is removed, the detection tab explains what to run, and the replay tab still works with the simulated sample and the **V5 schematic** model.

## Regenerating or adding media (optional)

Not needed to run the demo. `prepare_media.py` needs OpenCV (`pip install -r requirements-vision.txt`).

```bash
# 1. Detect marker ID 0 in every frame of a video
python vision/aruco_check.py --video path/to/clip.mp4 --scan \
    --dictionary DICT_4X4_50 --marker-id 0 --marker-mm 40 --out path/to/output
# 2. Copy the video and detections into demo/media/ and register the clip
python demo/prepare_media.py --video path/to/clip.mp4 \
    --detections path/to/output/clip_aruco_detections_all.csv \
    --clip-id my_clip --label "My clip" --camera fixed \
    [--default-range START END] [--invalid-segment FIRST LAST "Reason"] \
    [--environment "Water tank"] [--camera-description "..."]
# 3. Optional: V5 preview mesh from the CAD ZIP
python demo/prepare_media.py --cad-zip path/to/V5_CAD.zip
```

The committed clips were prepared this way. `camera_stable` used `--default-range 0 30` and `--invalid-segment 769 909 "Invalid for vessel tracking — marker detached"`. The water-tank clip used `--environment "Water tank" --camera-description "Handheld, approximately stationary camera"`.

### Committed media

| File in `media/` | SHA-256 (start) |
|---|---|
| `katamaran_10/video.mp4` | `3f5f4feca69ffb2d` |
| `katamaran_10/detections.csv` | `3a44a568c5b72e97` |
| `camera_stable/video.mp4` | `8d6740993a06db63` |
| `camera_stable/detections.csv` | `aba4960dc35f84ac` |
| `water_controlled/video.mp4` | `d0dc1da501ba50aa` |
| `water_controlled/detections.csv` | `cb4e778f303a2791` |

The videos are the team's own recordings (1024×576). They contain no location or device metadata. The presentation jump points are re-checked on load, so any that no longer match the media are disabled.

## Detection tab

- **The video's own timestamps are used.** `prepare_media.py` reads each frame's presentation time from the MP4 into `frame_times.json`. The demo maps video time to frame number with these, not with `frame / fps`.
  - `katamaran_10` has a variable frame rate: frames are usually 40 ms apart, with occasional 80 ms gaps.
  - The detection CSV's `time_s` column is nominal: frame 168 is listed at 7.007 s but is shown at 7.040 s. The page shows both values.
- **Checks when a clip is added:**
  - the CSV has the expected columns;
  - frame numbers are in range and unique;
  - every corner lies inside the *upright* frame, which catches CSVs made from sideways frames.

  In the browser, the overlay is turned off if the video's displayed size differs from the CSV's frame size.
- **Moving-camera clips** show detection status and corners only. No pose, roll or pitch is derived from them.
- **Range and invalid segments.** A clip can open on a default range (`--default-range START END` seconds); the **Range** menu also offers the full clip. Playback stops at the end of the range.
  - Frames marked with `--invalid-segment` show a red banner and a red band on the timeline, and the outline is dashed red. This applies even where the marker is still detected, because a detection there no longer describes the vessel.
  - The status line always reports what the detector found.

- **Clip metadata.** `--environment` (e.g. `Bench`, `Water tank`) and `--camera-description` are optional. When given, they appear in the source badge and the statistics panel. `--camera` stays `fixed` or `moving`.

### Detection statistics

The **Detection statistics** panel sits below the timeline and can be collapsed. It is computed in the browser (`js/stats.js`) from every recording's detection CSV and `frame_times.json`; no number is typed in.

- **Selected recording:** duration (last frame's time plus one typical frame interval), frames analysed, frames with and without marker ID 0, detection rate, and the environment and camera description.
- **Invalid segments:** for a recording with an invalid segment (`camera_stable`), the panel shows two rates:
  - the rate over **all frames**;
  - the rate over **valid frames only**, which excludes the invalid frames.
- **Comparison chart:** the detection rate of every recording. Hover a bar for exact counts; click a row to open that recording.
- **Scientific note:** the panel carries the note *"Detection rates reflect different camera viewpoints and recording conditions; they are not direct measures of vessel stability."*
- **Opening a recording directly:** `?clip=<id>` opens that recording first, e.g. `http://127.0.0.1:8765/?present&clip=water_controlled`.

| Recording | Frames | ID 0 detected | Rate |
|---|---|---|---|
| Bench — `katamaran_10` | 1007 | 492 | 48.9 % |
| Bench — `camera_stable`, all frames | 910 | 255 | 28.0 % |
| Bench — `camera_stable`, valid frames 0–768 | 769 | 125 | 16.3 % |
| Water Tank — Controlled Motion (`water_controlled`) | 1767 | 1532 | 86.7 % |

The rates are not like-for-like:
- **`camera_stable`:** the low fixed camera sees the flat marker almost edge-on.
- **Water tank:** the camera looks down onto the deck.
- **`katamaran_10`:** the camera moves and its distance to the marker changes.

None of these rates is a measure of roll, pitch, stability or recovery time.

### Clips prepared so far

| Clip | Menu label | Camera | Notes |
|---|---|---|---|
| `katamaran_10` | Bench — katamaran_10 (moving camera) | moving | Full clip, 1007 frames. Marker ID 0 detected in 492 frames. Detection status and corners only. |
| `camera_stable` | Bench — camera_stable (fixed camera) | fixed | Opens on **00:00–00:30** (frames 0–719). Full clip 00:00–00:37.9, 910 frames, variable frame rate (41.7–83.3 ms between frames). |
| `water_controlled` | Water Tank — Controlled Motion | moving (handheld, approximately stationary) | Full clip 00:00–01:13.6, 1767 frames, frames 40 ms apart with regular 80 ms gaps. Marker ID 0 detected in 1532 frames (86.7 %). No invalid segment. |

The two bench clips have the same video, CSV and timestamp files as the final submission package; only their menu labels and the `environment` / `camera_description` fields were added.

`water_controlled` details (times are the video's own timestamps):
- **Recording:** a real water-tank test filmed from above with a handheld phone, held as still as possible (not a tripod). The tethered vessel floats untouched at first; from about 16 s it is moved by hand.
- **Not sensor data:** the MPU6050 recording in `recordings/` is a bench recording, not water-test data.
- **Where detection holds:**
  - 0–16.6 s: 396 of 400 frames;
  - 16.7–43.4 s, while the vessel is moved by hand: 623 of 642 frames;
  - 60.2–73.6 s: 305 of 324 frames.
- **Detection lost, 43.44–49.16 s (frames 1042–1179):** 0 of 138 frames. The marker is in view and not covered, but its black border appears faded on one side; the video alone cannot tell glare from compression artefacts. A shorter loss of the same kind occurs at 22.08–22.80 s.
- **Intermittent, 55.28–60.12 s (frames 1326–1442):** 62 of 117 frames. The marker is strongly foreshortened.
- **Stray IDs:** the detector also reported ID 37 (frame 569) and ID 17 (frame 575). The demo uses ID 0 only.

`camera_stable` details:
- **Pitch tilt, about 4–7.5 s:** the end nearest the camera is lifted. The marker is then almost edge-on to this low camera and is **not detected**, so the demo shows "Marker not detected" with no outline.
- **Roll tilt, about 16–23 s:** the boat is rolled onto one pontoon. Marker ID 0 is detected in 123 frames.
- **Elsewhere in 0–30 s:** the marker lies almost flat as seen from the camera and is not detected.
- **Marker detached:**
  - frame-by-frame review shows the card on the deck through frame 768;
  - it slides off from frame **769** (32.08 s) and lies on the table from frame 778;
  - ID 0 is detected on the table from frame 780 to the end.

  Frames 769–909 are labelled **"Invalid for vessel tracking — marker detached"**.
- **Stray ID 17:** the detector also reported ID 17 in frames 623, 624 and 885. The demo uses ID 0 only and lists other IDs per frame.

**Adding a future fixed-camera clip:**
1. Run `vision/aruco_check.py --scan` on the video.
2. Run `prepare_media.py --camera fixed` with that video and CSV, adding `--default-range` or `--invalid-segment` if needed.
3. Pick the clip in the **Clip** menu.

Pose needs a calibrated camera and is not part of this demo.

### Presentation mode

### Engineering and Showcase views

The **Engineering | Showcase** switch (top right) changes the layout only. Both views use the same video, overlay, timeline and 3D canvas, so the selected recording and the playback position are kept, even during playback. `?view=showcase` opens the Showcase View directly (e.g. `http://127.0.0.1:8765/?view=showcase&clip=water_controlled`), and the last choice is remembered in the browser.

- **Engineering View:** the full technical interface described below.
- **Showcase View** (`js/showcase.js`, 1920×1080):
  - **ArUco tab, left:** the Bench → Water steps and the selected recording's highlights.
  - **ArUco tab, centre:** a larger video (512×910 at 1920×1080).
  - **ArUco tab, right:**
    - a large detection rate; `camera_stable` shows its valid-frames rate, with the all-frames rate beneath and labelled;
    - a current-frame indicator, including the invalid-segment flag;
    - a **marker close-up**, a magnified crop of the frame on screen with the CSV corners drawn on it. It appears only on detected frames.
    - a compact bench → water chart.
  - **3D tab:**
    - the vessel fills the stage;
    - the data-source label (*Recorded MPU6050 data* or *Simulated data*) and the roll/pitch values float over it, copied from the replay's own readouts;
    - the roll/pitch graph is taller.
  - **3D look:** the scene uses presentation lighting, soft shadows, tone mapping and fog. Geometry, data, axis mapping and timing are unchanged, and the original look is restored in the Engineering View.
  - **Technical notes:** limitations stay available under collapsible **Technical notes** in both tabs: ArUco is not a stability measurement; viewpoints differ; the MPU6050 axis mapping is unverified and the recording is from the bench; simulated data is not measured; the replay is not a hydrodynamic simulation.

**Layout (built for 1920×1080, no scrolling).**
- **Top row:** numbered steps show the progression *1 Bench · moving camera → 2 Bench · fixed camera → 3 Water tank*, each with its detection rate. The `camera_stable` step shows its valid-frames rate and says so.
- **Below the steps:**
  - the video, at full height;
  - the detector's result for the current frame;
  - the detection statistics: headline rate, counts, comparison chart and a four-step "How the numbers are produced" strip.
- **Technical notes:** longer explanations (pipeline, overlay, statistics, camera notes, shared-timeline status) are under the collapsible **Technical notes**.
- **Always visible:** the qualifications that must stay on screen are short lines in the panels: detection only, no pose, roll, pitch or stability; rates are not stability measures; invalid-segment banner and status.

**Highlights** are the eight verified jump points from `presentation.json`, grouped by recording:
- **Bench · moving camera:** 1
- **Bench · fixed camera:** 3
- **Water tank:** 4

The highlight bar shows only the selected recording's highlights and updates when the recording changes. In normal mode, **All highlights (8)** lists every group, and a highlight from another recording loads that recording. Each jump loads the clip and range, then pauses on the chosen frame.

**Presentation mode** (top right of the detection tab, or open `http://127.0.0.1:8765/?present`) keeps the same layout but hides secondary details: the **All highlights** list, the timeline legend and **Frame details** (collapsed). The 3D Motion Replay tab uses the same card layout. Only its HTML and CSS changed; its code, calculations and sample data did not.

| Jump | Clip | Frame | Video time | Shows |
|---|---|---|---|---|
| Close-up detected | katamaran_10 | 168 | 7.040 s | Marker ID 0 detected |
| Detection lost | camera_stable (00:00–00:30) | 144 | 6.042 s | Marker not detected (pitch tilt, marker edge-on) |
| Roll tilt detected | camera_stable (00:00–00:30) | 432 | 18.042 s | Marker ID 0 detected |
| Marker detached | camera_stable (full clip) | 840 | 35.042 s | Marker ID 0 detected **and** Invalid for vessel tracking — manually annotated |
| Floating vessel, marker detected | water_controlled | 144 | 6.040 s | Marker ID 0 detected |
| Hand-guided movement, marker detected | water_controlled | 800 | 33.360 s | Marker ID 0 detected |
| Marker visible, detection lost | water_controlled | 1100 | 45.840 s | Marker not detected (inside the 43.44–49.16 s loss) |
| Tilted marker, intermittent detection | water_controlled | 1370 | 57.120 s | Marker not detected (inside the 55.28–60.12 s flicker, 62 of 117 frames detected) |

When the page loads, each jump point is checked against the prepared media: the frame must be in range, within 1 s of the stated time, and the detection result and invalid-segment state must match. A point that does not match is disabled, with the reason shown. Invalid segments added with `--invalid-segment` are stored as `"annotation": "manual"`, because they come from a person's frame-by-frame review, not from the detector. Presentation mode does not touch the 3D replay.

## Replay tab

- **Sensor CSV loading** follows `sensor_log.load_recording`:
  - `roll_deg` and `pitch_deg` are required;
  - time comes from `timestamp_ms`, or else `time_s`;
  - rows without a time or roll value are dropped;
  - recordings are grouped by `run_id` and `source`.

  Use **Load sensor CSV…** for a recorded or exported file.
- **Source badges** follow the selected recording's `source` column:
  - `simulated` is shown as *Simulated data*;
  - `arduino_mpu6050` (e.g. `recordings/BENCH_HOME_01_annotated.csv`) is shown as *Recorded MPU6050 data*;
  - anything else is shown as *not confirmed as measured*.
- **Gaps are not filled.** A sample counts only within 1.5× the median sample interval. Otherwise the model turns into a grey outline with "No sensor sample at this time — attitude not shown" and blank readouts. Nothing is held over or interpolated.
- **Display convention:**
  - axes: X = bow, Y = up, Z = starboard;
  - **+ roll = starboard side down**, **+ pitch = bow up**.

  This is a display convention only: the MPU6050 axis mapping and signs on the boat are not bench-verified yet. The **Orientation check** panel tests the actual 3D attitude group: a pitch-only +5° raises the bow 8.72 mm and keeps the sides level, and a roll-only +5° lowers the starboard side 5.23 mm and keeps the bow level.
- **Model:**
  - **V5 CAD preview mesh** (visual only, nominal geometry) when prepared from the V5 ZIP;
  - otherwise the **V5 schematic** (simplified boxes from the nominal dimensions, not CAD).

  The mesh is port/starboard symmetric. The pivot (midship, 40 mm above the keel) and the grid are display references, not a waterline or a measured draft.

## Files

| Path | Purpose |
|---|---|
| `index.html`, `css/style.css`, `js/*.js` | The page (`data.js` parsing, `detection.js` tab 1, `stats.js` detection statistics, `showcase.js` Showcase View, `presentation.js` presentation mode, `replay.js` and `attitude.js` tab 2) |
| `presentation.json` | The eight presentation jump points |
| `prepare_media.py` | Adds a clip or the CAD mesh to `media/` and `media/manifest.json` |
| `serve.py` | Local server with correct content types |
| `make_simulated_sample.py` | Regenerates `samples/simulated_motion_sample.csv` with the dashboard's own `sensor_log` |
| `test_demo_tools.py` | pytest tests for the Python tools and the sample. When `media/` is prepared, they also check: bench files byte-identical to the submission, the verified counts of all three recordings, every jump point, and — in headless Chrome or Edge, if installed — that the statistics the page displays match the CSVs |
| `vendor/three/` | Three.js r160 (MIT) and `VERSION.txt` with checksums |
