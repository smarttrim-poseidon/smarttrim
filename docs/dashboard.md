# SmartTrim V5 tank-test dashboard (Streamlit)

`app.py` is an offline-first dashboard for the tank tests. It shows CAD draft estimates, cargo cases, manual draft readings, saved-run comparison, live Arduino recording, sensor CSV replay and rule-based alert explanations. Simulated, CAD, manual and sensor values are labelled separately.

The dashboard has no route-density comparison and no off-centre cargo or heel alert; cargo TCG is shown as a number only.

## V5 and the physical capacity check

V5 is the primary test configuration: two nominal 200 × 48 × 65 mm pontoons,
120 mm centreline spacing and a 65 mm seam reference. V3 remains selectable as
the fallback; its waterplane inputs are unverified, so the app does not show a
V3 draft prediction. V5 CAD estimates are upright still-water estimates, not
measured draft, trim, wave response, or local freeboard at a tilted corner.

The attributed `v5_capacity.json` subset is copied from
`V5_CAD_Verification_and_Hydrostatics.json` in the V5 ZIP. Its
`capacity_still_water` curve is for both pontoons together, with freshwater
reference density 1000 kg/m³; no second pontoon multiplier is applied. The
printed core CAD mass is 308.1 g, excluding other assembly parts and not a
weighed assembled mass.

Weigh the complete dry assembled boat and enter that actual mass before
estimating, then record how it was weighed. Each mass is counted once:

- **Measured dry base mass**: the dry assembled boat on the scale, without
  cargo. It includes the Nano, MPU6050 and wiring only if they were on board.
- **How was the dry base weighed?**: choose **Electronics included** if they
  were on board, or **Electronics weighed separately** if they were weighed off
  the boat. **Not recorded** (the default) leaves the total mass and CAD
  draft/freeboard pending.
- **Measured electronics mass** and its X/Y/Z position: shown and used only
  with **Electronics weighed separately**. A blank mass leaves the total and CAD
  estimate unavailable. A blank coordinate only affects the matching centre of
  mass. Measure the base centre of mass on the same boat that was weighed.
- **Measured active cargo mass**: the one weighed cargo block. The cargo case
  (150, 250, 350 or 400 g) is only a label; the calculation uses the mass
  entered here.

Manual draft and trim do not depend on these mass inputs. Saved runs and sensor
CSVs record the weighing basis and electronics values. Older CSVs without them
load as "not_recorded".

The run comparison checks only the documented dry boat mass (base, plus
electronics if weighed separately) and the cargo case, mass and X/Y/Z. Missing
values give "unknown", never a match. Equal dry mass does not confirm equal
weight distribution: the base and electronics positions are not compared, so
confirm the electronics were not moved between runs.

Test base-only, then one 150 g, 250 g, 350 g or 400 g cargo block at a
time, progressively and only as Olga permits after checking measured freeboard
and leaks. 400 g is the organisers' maximum planned cargo. Both slack mooring
options are recorded. Keep the four manual draft readings independent from
sensor roll/pitch. Measured trim is aft minus forward (positive means the stern
is deeper). Transverse draft difference is starboard minus port, in mm.

**Measured tank water depth (m)** is optional test metadata for the run. Leave
it blank until the team measures it. It is saved with the manual run and the
sensor CSV as `tank_water_depth_m` and shown when a recording is replayed. Older
CSVs load with it blank. It is not used by the CAD draft estimate or by the
under-keel clearance alert, which keeps its own water depth input.

## Running the dashboard

```bash
pip install -r requirements.txt
python -m pytest -q
streamlit run app.py
```

The sensor CSV protocol is `timestamp_ms,roll_deg,pitch_deg` at 115200 baud;
`timestamp_ms` is Arduino `millis()`. Confirm the actual board axis mapping and
signs with flat, pitch-only and roll-only bench readings before water tests.
The dashboard works offline without an Arduino, and simulated, CAD, manual and
sensor values are labelled separately.

`recordings/BENCH_HOME_01_annotated.csv` is a 75 s, 50 Hz bench recording from
the Arduino Nano + MPU6050 with the sensor attached to a book and tilted by
hand. It was not on the boat or in water. It shows hardware-software
integration only, not vessel stability or validated sensor accuracy; the axis
signs are still unverified. It loads in **Recorded CSV** and in the 3D Motion
Replay (**Load sensor CSV…**).

When no water depth is entered, the dashboard shows an under-keel clearance
alert. **Explain missing-depth alert** gives a fixed, rule-based explanation
from `alert_explainer.py` (labelled "Rule-based explanation"): missing water
depth is the cause, and the approved operator check is to verify the charted
depth and water-level corrections. No external service or API key is used.

