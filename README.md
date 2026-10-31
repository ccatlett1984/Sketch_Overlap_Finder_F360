# Sketch Overlap Finder for Fusion 360

A Fusion 360 add-in that finds **duplicate and overlapping sketch curves**: lines stacked on top of each other, short segments hidden under longer ones, and collinear lines or arcs that partly overlap. These are the usual reasons a profile won't close, an extrude fails, or CAM cuts the same path twice.

The add-in highlights every overlap in the canvas. You can step through them one at a time with zoom, and it can optionally clean them up for you.

## Features

| Finding | Highlight | Meaning |
|---|---|---|
| **Duplicate** | Red | Two curves lying exactly on top of each other (same or reversed direction) |
| **Covered** | Orange | A shorter curve lying fully on top of a longer one |
| **Partial overlap** | Magenta | Two collinear lines, or arcs on the same circle, sharing part of their length |

- **Lines:** checked against lines for duplicate, covered and partial overlap.
- **Arcs and circles:** checked against arcs and circles with the same center and radius, including overlaps that cross the 0° angle.
- **Splines, ellipses and conics:** checked for exact duplicates only.
- **Not reported:** curves that only touch end-to-end, or that cross each other.
- **Speed:** uses sweep-and-prune, so sketches with thousands of curves still check quickly.
- **Step through:** pick any finding from the list to highlight it in cyan and zoom to it.
- **Optional cleanup when you click Done** (one undo step):
  - **Delete exact duplicates.** Keeps the copy with the most constraints and dimensions, removes construction copies first, and never deletes projected geometry.
  - **Delete fully covered segments.** Removes the shorter curve.
  - **Select remaining overlapping curves.** Leaves them selected so you can fix them by hand.

## Installation

1. Download or clone this repository. The folder must stay named `Sketch_Overlap_Finder_F360`, because Fusion requires the folder name to match the `.py` and `.manifest` files.
2. In Fusion 360, open **Utilities → Add-Ins** (Shift+S) and go to the **Add-Ins** tab.
3. Click the **+** next to *My Add-Ins* and select the `Sketch_Overlap_Finder_F360` folder.
4. Select the add-in, click **Run**, and tick **Run on Startup**.

You can also copy the folder into:

```
%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\
```

## Usage

1. Open the sketch you want to check.
2. Click **Sketch → Modify → Find Overlapping Curves**. The command is also in the **Inspect** panel, where you can pick any sketch in the design.
3. The summary shows how many duplicates, covered segments and partial overlaps it found, and all of them are highlighted.
4. Choose an entry under **Show** to zoom to it. Choose **All** to see every finding again.
5. Click **Done**, with any cleanup options you want turned on.

### Settings

| Setting | Default | Notes |
|---|---|---|
| Distance tolerance | 0.01 mm | How close two curves must be to count as overlapping |
| Angle tolerance | 0.01° | How parallel two lines must be |
| Projected / reference curves | On | Pairs where *both* curves are projected are always ignored, since there's nothing to fix in the sketch |
| Construction curves | Off | Construction centerlines drawn over real geometry are usually intentional |
| Splines / ellipses | On | Exact-duplicate check only |

## Project layout

```
Sketch_Overlap_Finder_F360.py        Fusion command, UI, highlighting, cleanup
Sketch_Overlap_Finder_F360.manifest  Add-in manifest
lib/overlap_core.py                  Pure-Python geometry (no Fusion dependency)
tests/test_overlap_core.py           Unit tests for the geometry core
resources/FindOverlaps/              Toolbar icons
```

## Development

The geometry checks live in `lib/overlap_core.py` and don't import Fusion, so you can test them with any Python 3.9+:

```powershell
python .\tests\test_overlap_core.py
```

The add-in reloads `overlap_core` each time it starts. After editing it, stop and run the add-in again from the Add-Ins dialog.

## License

Copyright (C) 2026 ccatlett1984

This program is free software: you can redistribute it and/or modify it under the terms of the **GNU Affero General Public License v3.0**. See [LICENSE](LICENSE) for the full text.
