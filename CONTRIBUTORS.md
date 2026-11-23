# Contributors

SmartTrim / POSEIDON was developed by **Olga [SURNAME TBC]**, **Elisavet Tsifopanopoulou** and **Zoi Theofilakou**.

This file records who was responsible for what. It is based on the team's own account of its work, agreed by all three members. Git history is **not** a reliable source: this repository was assembled from a private development repository, and some original work was merged there through combined commits.

## Subsystem responsibility

| Area | Olga | Elisavet | Zoi |
|---|---|---|---|
| Mechanical architecture, V3/V5 geometry and CAD, SolidWorks verification | **Responsible** | | |
| Hydrostatic and mechanical calculations (engineering) | **Responsible** | | |
| Physical prototype, 3D printing, assembly, weighing, physical validation | **Responsible** | | |
| Arduino Nano + MPU6050 hardware and sketch | | **Responsible** | |
| Serial communication and sensor data acquisition | | **Responsible** | Later integration |
| Sensor placement on the boat | Mechanical side | Sensor side | |
| Computer vision | | | **Responsible** |
| Sensor replay and recorded/simulated data labels | | Original sensor data and format | **Responsible** |
| Alert logic and rule-based explanations | Approved operator-check wording | | **Responsible** |
| Testing, debugging, integration, release packaging | Physical testing | Sensor testing | Software (led) |
| Browser demo | Shared | Shared | Shared |
| Final system preparation and validation, presentation, videos, delivery | Shared | Shared | Shared |

## Files

| File | First implementation | Later development |
|---|---|---|
| `calculations.py`, `test_calculations.py` | Olga | Olga and Zoi |
| `app.py` | Elisavet | Elisavet and Zoi |
| `arduino/smarttrim_mpu6050.ino` | Elisavet | |
| `arduino_serial.py`, `test_arduino_serial.py` | Elisavet | Integration changes |
| `sensor_log.py`, `test_sensor_log.py` | **[SPLIT TBC]** Recording format: Elisavet. Replay and source labels: Zoi. | |
| `alert_explainer.py`, `test_alert_explainer.py` | Zoi | |
| `vision/aruco_check.py` | Zoi | |
| `vision/cv_draft.py`, `vision/test_cv_draft.py`, `vision/README.md` | Zoi | |
| `demo/` (HTML, CSS, JavaScript, Python tools, tests) | Olga, Elisavet and Zoi | |
| `v5_capacity.json` | Olga (subset of her V5 CAD verification data) | |
| `demo/media/cad/v5_preview.stl` | Olga (V5 CAD preview mesh) | |
| `recordings/BENCH_HOME_01_annotated.csv` | Elisavet (acquisition) | Annotation **[TBC]** |
| `demo/media/*/video.mp4` | Team recordings | |
| `demo/media/*/detections.csv` | Produced by `vision/aruco_check.py` | |
| `demo/vendor/three/` | Three.js authors (MIT), unmodified | |

Items marked **TBC** are still being confirmed and will be updated before publication.
