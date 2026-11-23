# Third-party notices

## Vendored (included in this repository)

| Component | Version | Licence | Location |
|---|---|---|---|
| three.js (`three.module.min.js`, `OrbitControls.js`, `STLLoader.js`) | r160 (npm `three@0.160.0`), unmodified | MIT. Copyright © 2010–2023 three.js authors | [`demo/vendor/three/`](demo/vendor/three/) (licence: [`LICENSE`](demo/vendor/three/LICENSE), checksums: [`VERSION.txt`](demo/vendor/three/VERSION.txt)) |

## Python dependencies (installed with pip, not included)

| Package | Licence | Used by |
|---|---|---|
| Streamlit | Apache-2.0 | Dashboard |
| pandas | BSD-3-Clause | Dashboard, sensor CSVs |
| pyserial | BSD-3-Clause | Arduino serial link |
| pytest | MIT | Tests |
| OpenCV (`opencv-python-headless`) | Apache-2.0 (OpenCV 4.5+) | `vision/`, `demo/prepare_media.py` |
| NumPy | BSD-3-Clause | `vision/`, `demo/prepare_media.py` |

The Arduino sketch uses the Arduino `Wire` library (LGPL-2.1), which is part of the Arduino core and not included here.
