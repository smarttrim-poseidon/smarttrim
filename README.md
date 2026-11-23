# SmartTrim / POSEIDON

**A twin-pontoon model vessel with an onboard motion sensor, a tank-test dashboard and a browser demo for replaying tests and reviewing computer vision results.**
Built by a team of three for a maritime engineering challenge in November 2026.

**[▶ Live browser demo](https://ORG.github.io/REPO/)** · [Team contributions](#team-contributions) · [Limitations](#limitations)

<!-- PUBLICATION TODO: replace ORG/REPO, Olga's surname and the profile links before the first push. -->

SmartTrim is a prototype for a tank test. It is not a navigation or safety system.

---

## What is in this repository

| Part | What it does | Where |
|---|---|---|
| **Mechanical design (V5)** | Two 200 × 48 × 65 mm pontoons at 120 mm centreline spacing. Nominal CAD hydrostatics give an upright, still-water capacity curve. | [`v5_capacity.json`](v5_capacity.json), [`demo/media/cad/`](demo/media/cad/) |
| **Sensor system** | Arduino Nano + MPU6050. A complementary filter outputs roll and pitch at about 50 Hz as `timestamp_ms,roll_deg,pitch_deg` over serial at 115200 baud. | [`arduino/`](arduino/), [`arduino_serial.py`](arduino_serial.py) |
| **Tank-test dashboard** (Streamlit) | CAD draft and seam-freeboard estimates, cargo cases, manual draft readings, saved-run comparison, live Arduino recording, sensor CSV replay and rule-based alert explanations. | [`app.py`](app.py), [`calculations.py`](calculations.py), [`sensor_log.py`](sensor_log.py), [`alert_explainer.py`](alert_explainer.py), [docs](docs/dashboard.md) |
| **Browser demo** (static, offline) | *ArUco Detection Review*: three real recordings with per-frame marker detection and statistics. *3D Motion Replay*: the V5 model driven by recorded or simulated roll and pitch. | [`demo/`](demo/) ([details](demo/README.md)) |
| **Computer vision** (classical OpenCV, no ML) | ArUco marker detection on video, plus a draft-from-photo prototype that reads where the waterline crosses printed rulers. | [`vision/`](vision/) ([details](vision/README.md)) |

## Quick start

Requires Python 3.10+ (developed on 3.11).

```bash
git clone https://github.com/ORG/REPO.git
cd REPO
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt -r requirements-vision.txt
# or, for the exact versions the tests were verified with:
# pip install -r requirements-lock.txt
```

| Task | Command |
|---|---|
| Browser demo | `python demo/serve.py`, then open <http://127.0.0.1:8765/> |
| Dashboard | `streamlit run app.py` (works without an Arduino) |
| Tests | `python -m pytest` |
| ArUco detection on a video | `python vision/aruco_check.py --video clip.mp4 --scan` |

The browser demo needs no Python packages. Any static file server works, and it is also deployed to GitHub Pages by [`.github/workflows/pages.yml`](.github/workflows/pages.yml).

**Forks:** to get your own live demo, enable Actions in the fork, then go to *Settings → Pages → Source: GitHub Actions*. All paths are relative, so the demo works under any repository name.

## Results in this repository

| Evidence | Status |
|---|---|
| Upright, still-water draft and seam freeboard from nominal V5 CAD | Estimates, not measurements |
| MPU6050 recording (`recordings/BENCH_HOME_01_annotated.csv`, 75 s, 50 Hz) | Real data, recorded on a **bench** with the sensor attached to a book. Not on the boat, not in water. Axis signs unverified. |
| ArUco detection, marker ID 0 | Bench, moving camera: 492/1007 frames (48.9 %). Bench, fixed low camera: 255/910 (28.0 %), or 125/769 (16.3 %) on valid frames only. Water tank: 1532/1767 (86.7 %). These are **detection rates**, not accuracy, pose or stability measures, and the viewpoints differ. |
| Draft-from-photo | Synthetic-image tests, plus one dry bench photo (+0.86 mm against a by-eye reading). **Not validated on real waterline photos.** |
| Alert explanations | Deterministic and rule-based. An earlier version that used a language model was replaced before submission. |

## Team contributions

SmartTrim / POSEIDON is a team project. Each member led one subsystem; integration and delivery were shared.

| Member | Role | Individual responsibilities |
|---|---|---|
| **Olga [SURNAME TBC]** | Mechanical engineering and architecture | Complete mechanical architecture and structural design. V3/V5 geometry and V5 CAD. SolidWorks verification. Hydrostatic and mechanical calculations. Started the calculations module (`calculations.py`). Physical prototype design, 3D printing and assembly. Physical measurements, weighing and engineering validation. Mechanical aspects of sensor placement. |
| **Elisavet Tsifopanopoulou** | Sensors, connections and hardware–software integration | Arduino Nano + MPU6050 system and the Arduino sketch. Serial communication (first `arduino_serial.py`). Sensor data acquisition and recording. Sensor testing and debugging. First implementation of the Streamlit dashboard (`app.py`). |
| **Zoi Theofilakou** | Software development, computer vision and integration | Computer vision: ArUco detection (`vision/aruco_check.py`) and the draft-from-photo prototype (`vision/cv_draft.py`). Sensor replay and recorded/simulated data labelling. Alert logic and rule-based alert explanations. Continued development of `calculations.py` with Olga and of `app.py` with Elisavet. Testing, debugging, integration and release packaging. |

**Shared by all three:** the browser demo, integration of the mechanical, sensor and software parts, final system preparation and validation, the presentation, the videos and the final delivery.

File-level detail is in [CONTRIBUTORS.md](CONTRIBUTORS.md). This repository was assembled from the team's private development repository, so its Git history does not show who wrote what. Some of the original work was merged through combined commits.

<!-- PUBLICATION TODO: add each member's GitHub/LinkedIn link -->

## Limitations

- Draft and freeboard are upright, constant-waterplane-area CAD estimates. Waves, heel and trim are not modelled. Heel uses an assumed GM.
- No physical water-test sensor data is included. The MPU6050 recording is from a bench. The MPU6050 axis mapping and signs on the boat have not been physically verified.
- The 3D replay is a visual replay of roll and pitch, not a hydrodynamic simulation. The default sample is simulated and labelled as such.
- ArUco detection finds the marker and its corners only: no pose, roll, pitch or stability. The video and sensor timelines are not synchronised.
- The draft-from-photo prototype has not been validated on real waterline photos.

## Repository layout

```
app.py, calculations.py, sensor_log.py,      Streamlit dashboard and its modules
alert_explainer.py, arduino_serial.py
test_*.py                                    pytest suites for the modules above
v5_capacity.json                             V5 CAD capacity curve (subset of the V5 verification data)
arduino/                                     Arduino Nano + MPU6050 sketch
recordings/                                  Bench MPU6050 recording
demo/                                        Static browser demo (deployed to GitHub Pages)
vision/                                      OpenCV tools and tests
docs/                                        Dashboard documentation
```

## Licence

**Not yet selected.** Until the team chooses a licence, all rights are reserved by the three contributors. See [LICENSE-PENDING.md](LICENSE-PENDING.md). Third-party components keep their own licences: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Citation

If you reference this project, use the metadata in [CITATION.cff](CITATION.cff) (GitHub's *Cite this repository* button).
