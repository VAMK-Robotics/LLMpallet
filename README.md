# LLMpallet

Web-based box palletizing software for an EUR pallet (1200 × 800 mm). It calculates the centre of the
top face of every box and shows the result in a 3D preview. When you press **Generate CSV**, it sends
the positions as a CSV file to an ABB OmniCore controller over RWS 2.0 and writes the box dimensions
to RAPID variables. The design is described in [PLAN.md](PLAN.md).

## Start

Windows: double-click `run.bat`. It creates a virtual environment the first time, then opens
http://127.0.0.1:8000.

Manually:

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

To use the GUI from another computer, start uvicorn with `--host 0.0.0.0`. There is no login on the
GUI itself, so only do that on a trusted network.

Tests: `.venv\Scripts\python -m pytest`

## Coordinate system

Same as the robot workobject:

* **Origin:** the bottom-right corner of the pallet seen from above, on the top deck surface.
* **Axes:** +X along the 1200 mm edge, +Y along the 800 mm edge, +Z up. In the **Top** view, X points
  up the screen and Y to the left.
* **Rotation 0°:** box length (`nBoxX`) along X and width (`nBoxY`) along Y. Rotations are −90, 0, 90
  and 180°. In the preview, the small arrow on top of each box shows the box's own +X direction.
* **Box Z:** the top of the box, `layer·height + interlayers`.

## Patterns

Each layer has its own pattern. Pick the layer in the drop-down, or click a box in the preview.

| Pattern | Description |
|---|---|
| Column | Grid, all boxes in the chosen rotation |
| Interlocked | Block pattern, every second layer turned 90° |
| Pinwheel | Four blocks around the centre, block *k* turned *k*·90° from the chosen rotation |
| Tetris | The optimizer finds the layout with the most boxes. You choose which rotation the lengthwise and crosswise boxes use |

**Placing order.** The robot stands at the origin corner, so every layer is filled from the far corner
toward the origin, bottom layer first. The CSV rows follow this order.

**Allowed overhang.** This is the largest share (%) of a box's bottom area that may hang over nothing.
Above the first layer, a position is used only if at least (100 − limit) % of the box rests on boxes
in the layer below. Other positions are left out and shown as red dashed outlines. Tetris layers pick
the candidate layout with the most supported boxes.

**Partial last layer.** Its boxes are either centred, or packed from the start corner.

## CSV

```
1000.0,550.0,200.0,0.0
1000.0,250.0,200.0,0.0
...
```

`X,Y,Z,rotation`, one decimal, LF line endings, no header. A copy is saved in `output/`.

## Robot controller

Configure the controller on the **Robot settings** page:

* protocol, IP address, HTTP and HTTPS ports
* user name and password
* CSV directory (default `HOME:/CSV/`)
* task, module and variable names (defaults `T_ROB1`, `MainModule`, `nBoxX/nBoxY/nBoxZ`)

Changes are saved automatically to `config/config.json`. The password is stored there in plain text,
so protect that folder.

Requirements on the controller:

* The variables must be declared in the module as `VAR num` or `PERS num`, e.g.
  `PERS num nBoxX := 0;`.
* The RWS user needs the UAS grants for writing files and modifying RAPID data.
* Edit mastership must not be held by someone else (FlexPendant program editor, RobotStudio).

Generate CSV performs these steps and shows the result of each one:

1. login (`GET /rw/system`)
2. create the directory if missing
3. upload the file (`PUT /fileservice/$HOME/CSV/<file>`)
4. request edit mastership
5. write and read back the three variables
6. release mastership, then logout
