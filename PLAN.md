# LLMpallet – Implementation Plan

Web-based box palletizing software. It computes the top-centre position and rotation of every box on a
EUR pallet (1200 × 800 mm). It shows the result in an interactive 3D preview. When asked, it writes the
positions to a CSV file and sends that file, plus the box dimensions, to an ABB OmniCore controller
(RobotWare 7.21.5, RWS 2.0). No robot programs are part of this project.

## 1. Architecture

```
Browser (static HTML/JS)            Python backend (FastAPI)                 OmniCore controller
─────────────────────────           ───────────────────────────              ─────────────────────
Palletizer page: parameters  ──►    POST /api/layout   (pattern engine)
3D preview (Three.js)               POST /api/generate (CSV + RWS)    ──►    /fileservice → HOME:/CSV/
Settings page (autosave)     ──►    GET/PUT /api/config (config.json)  ──►   /rw/rapid/symbol → nBoxX/Y/Z
                                    POST /api/test-connection
```

* **Backend:** Python 3.11+, FastAPI and uvicorn, `httpx` for RWS, `pydantic` for validation.
  It holds the only implementation of the pattern engine, so the preview and the CSV always match.
* **Frontend:** plain ES modules, no build step. Three.js (with OrbitControls and CSS2DRenderer) is
  bundled in `frontend/vendor`, so the app works without internet on the cell network.
* **Why a backend:** the controller has no CORS for our origin, uses a self-signed certificate, and
  the credentials must not live in the browser.

```
backend/
  main.py            FastAPI app, routes, static file serving
  models.py          pydantic models (params, layer config, robot settings)
  config_store.py    config/config.json load/save (atomic), password masking
  rws_client.py      RWS 2.0 client (login, fileservice, mastership, RAPID symbols, logout)
  engine/
    geometry.py      pallet constants, rotation helpers
    patterns.py      column, pinwheel, guillotine optimizer ("tetris")
    layout.py        layers, Z, placement order, partial layers, validation
    csv_export.py    CSV formatting
frontend/
  index.html, css/style.css
  js/{app.js, api.js, preview3d.js, settings.js}
  vendor/three/...
tests/               pytest: engine, csv, rws (httpx MockTransport)
config/config.json   created at runtime (git-ignored)
output/              local copy of every generated CSV (git-ignored)
```

## 2. Coordinate system

* **Origin** is the bottom-right corner of the pallet seen from above. +X runs along the 1200 mm edge,
  +Y along the 800 mm edge, +Z points up. To be right-handed like an ABB workobject, the top view has
  the 1200 mm edge vertical on screen: X points up the screen and Y points left. The preview's
  "Top" view follows this.
* **Z = 0** is the pallet's top deck surface. The pallet body (144 mm) is drawn below Z = 0, for the
  picture only.
* **Rotation** is about +Z. At 0° the box *length* (`nBoxX`) runs along X and its *width* (`nBoxY`)
  along Y. ±90° swaps the footprint. 180° has the same footprint as 0°. Allowed values: −90, 0, 90, 180.
* **Output point** is the centre of the box's top face.
* **Height of layer i** (0-based): `z_top(i) = (i+1)·H + (i + b)·t`, where t is the interlayer
  thickness and b = 1 if "interlayer under first layer" is enabled, otherwise 0. By default there is
  interlayer only between layers.
* **Usable area** is `[bx, 1200−bx] × [by, 800−by]`. No overhang. Each layer's pattern is centred in
  the usable area.
* **Gaps:** every footprint is grown by the gap, and so is the usable area. This gives exact counts
  without a gap at the outer edges.

## 3. Pattern engine

Settings for each layer: pattern, rotation, and the two rotations used by the optimizer.

| Pattern | Algorithm | Rotation |
|---|---|---|
| Column | Uniform grid | User: −90/0/90/180 |
| Interlocked | Block (grid) pattern. Each layer is turned 90° relative to the one below: even layers (1st, 3rd, …) use the chosen rotation, odd layers use rotation + 90°. | User: −90/0/90/180 (base) |
| Pinwheel | Four blocks around the centre, point-symmetric, each block turned 90° from the previous one. Block sizes are searched by enumeration. | User picks block 1's rotation; blocks 2–4 get +90, +180, +270. All four directions occur, so a marked side can face out. |
| Optimized ("tetris") | Best of: recursive guillotine dynamic program over the "normal" positions (both orientations), and the pinwheel search. Most boxes wins. | User picks the rotation for lengthwise boxes (0/180) and crosswise boxes (90/−90) |

**Box count and layers.** Layers are filled in order up to their capacity until the total is reached.

* *Error* (Generate is blocked) if the total is more than the combined capacity, or a layer can't hold
  even one box.
* *Warning* for a partial last layer, or for layers left empty.

**Partial layer** option, chosen by the user:

* `centered`: use the positions closest to the pallet centre.
* `start_corner`: use the first positions in placement order, i.e. packed from the start corner.

**Placement order.** The robot stands at the origin corner, so each layer is filled from the far
corner (max X, max Y) toward the origin, and a new box is never placed beyond an already placed one.

* A box lies behind another when it is completely farther from the origin along X while overlapping
  it in Y, or the same along Y with X overlapping. Behind boxes always come first, which matters for
  mixed patterns such as pinwheel and tetris.
* Among the boxes that are free to place, the default picks the highest X first (by the box's near
  edge), then the highest Y.
* Option: primary axis Y instead of X.
* Layers that are identical are computed only once.
* Layers go bottom to top. CSV row 1 is the first box placed.

## 4. CSV

* One row per box: `X,Y,Z,R`, each with exactly one decimal (`75.0,100.0,80.0,0.0`).
* `.` as the decimal separator, no header, LF line endings, `-0.0` written as `0.0`.
* The file name defaults to `pallet.csv` and can be changed in the GUI. It is checked to be a safe
  name, and `.csv` is added if missing.
* The file is generated only when **Generate CSV** is pressed. A local copy goes to `output/`.

## 5. RWS 2.0 client

Reference: https://developercenter.robotstudio.com/api/RWS. Check every request here against it on
the real controller.

* **Connection:** protocol HTTPS (OmniCore default) or HTTP (for example a virtual controller), using
  the HTTP or HTTPS port from settings. Option to accept a self-signed certificate.
* **Headers:** `Accept: application/hal+json;v=2.0`,
  `Content-Type: application/x-www-form-urlencoded;v=2.0` for form posts.
* **Auth:** HTTP Basic on the first request (`GET /rw/system`), then the session cookies. On 401 the
  request is retried once with credentials. Always finishes with `GET /logout`.
* **Directory:** `HOME:/CSV/` becomes `$HOME/CSV`. Each path segment is checked with
  `GET /fileservice/...` and created if missing with `POST /fileservice/<parent>` and
  `fs-newname=<seg>&fs-action=create`.
* **Upload:** `PUT /fileservice/$HOME/CSV/<file>` with the CSV as the body, overwriting any existing
  file. If the controller answers 415, the upload is retried with another content type.
* **Variables:** request edit mastership with `POST /rw/mastership/edit/request`. Then for each
  variable send `POST /rw/rapid/symbol/RAPID/<task>/<module>/<var>/data` with `value=<num>`, and read
  it back with GET to verify. Mastership is always released (`POST /rw/mastership/edit/release`) in
  a `finally` block.
* **Robot side:** `nBoxX/Y/Z` are `VAR num` or `PERS num` (not `CONST`). The user needs UAS grants
  for file write and RAPID data modification.
* **GUI report:** each step is shown as success or failed, with the error text from the controller.

## 6. GUI

* **Palletizer page**
  * Inputs: box length (X), width (Y), height (Z), total boxes, layer count, gap, border X, border Y,
    interlayer thickness, interlayer under first layer, partial layer mode, placement primary axis,
    CSV file name.
  * Layer panel: active layer drop-down; pattern and rotation selects for that layer; "apply to all
    layers" button.
  * 3D preview:
    * EUR pallet model, boxes, interlayers, a top-centre marker on each box, XYZ axes at the origin.
    * OrbitControls: left mouse rotates, right mouse pans, wheel zooms. View buttons: Top, Iso, Front.
    * Clicking a box selects its layer. The active layer is highlighted and the others are faded.
      Hover shows a tooltip with index, X, Y, Z and R. Order numbers can be shown on the active layer.
  * Any change recomputes the layout (debounced) and autosaves the job.
  * Info: count, capacity and Z per layer; total height; warnings and errors; coordinates table for
    the active layer.
  * Generate CSV button with a step-by-step status log and a download of the generated file.
* **Settings page:** protocol, IP, HTTP port, HTTPS port, username, password, verify certificate,
  timeout, CSV directory, task, module, variable names, default file name. Changes are saved
  automatically to `config/config.json`. The password is never sent back to the browser. A Test
  connection button is included.

## 7. Testing

* **Engine:**
  * known capacities
  * all boxes inside the borders
  * no overlaps (including the gap)
  * Z with interlayer
  * order runs from the far corner toward the origin
  * interlocked alternates
  * pinwheel uses all four rotations
  * both partial modes
* **CSV:** formatting, `-0.0`, row order.
* **RWS:** mock transport checks the call sequence, paths, headers, that mastership is released on
  failure, and that logout always runs.
* **Manual:** RobotStudio virtual controller (RW 7.21) over HTTP, then the real OmniCore over HTTPS.
  Jog to box #1 and compare.
