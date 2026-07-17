"""
Circle Debug Visualization
--------------------------
Produces a labeled overlay image showing every circle the detector found,
colour-coded by status:

  GREEN  — resolved: a detected callout sits within 1.5 radii of this circle
  BLUE   — recovered by Strategy D (ref=8 in the current test job)
  ORANGE — unresolved: no callout nearby (candidates for missing refs 4, 9, etc.)
  DASHED — border-zone circles (y < 10% or y > 90% of image height)

Every circle is labelled with a candidate ID (C0, C1, …) and its centre
coordinates so we can answer definitively whether circles for refs 4 and 9
are present in the detector output.

Run from the ai-worker directory:
    venv/Scripts/python circle_debug_visualization.py

Output image saved to:
    ../storage/outputs/<job_id>/assembly_1/circle_debug.png
"""

import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

# ── Paths ──────────────────────────────────────────────────────────────────────
JOB_DIR      = Path("../storage/outputs/e039a267-7cd3-472b-adaf-89a9074770b8")
ASSEMBLY_DIR = JOB_DIR / "assembly_1"
DIAGRAM_PATH = ASSEMBLY_DIR / "diagram.png"
BOM_PATH     = ASSEMBLY_DIR / "bom_raw.json"
OCR_PATH     = ASSEMBLY_DIR / "ocr_results.json"
OUT_PATH     = ASSEMBLY_DIR / "circle_debug.png"

# Must match strategy_d_recovery._RESOLVED_PROXIMITY_RATIO
_RESOLVED_PROXIMITY_RATIO = 1.5

# Strategy D recovery result (from previous diagnostic run — ref=8 at circle(1208,2165))
# We identify the Strategy-D circle by matching centre coordinates.
_STRATEGY_D_RECOVERED = {
    "8": (1208, 2165),
}

# ── Colours (BGR) ─────────────────────────────────────────────────────────────
COL_RESOLVED  = (60, 180, 60)     # green
COL_STRATEGY_D = (200, 100, 0)    # blue
COL_UNRESOLVED = (0, 130, 255)    # orange
COL_BORDER    = (160, 160, 160)   # gray
COL_TEXT      = (20, 20, 20)      # near-black label text
COL_TEXT_BG   = (255, 255, 255)   # white label background

FONT       = cv2.FONT_HERSHEY_SIMPLEX
FONT_SCALE = 0.55
THICKNESS  = 2


def _is_strategy_d(circle: dict) -> str | None:
    """Return the recovered ref number if this circle is the Strategy-D hit."""
    for ref, (dx, dy) in _STRATEGY_D_RECOVERED.items():
        if circle["x"] == dx and circle["y"] == dy:
            return ref
    return None


def _nearest_callout_dist_ratio(circle: dict, callouts: list[dict]) -> float:
    """Return distance/radius to the nearest existing callout."""
    if not callouts:
        return float("inf")
    cx, cy, r = circle["x"], circle["y"], circle["radius"]
    return min(
        math.sqrt((cx - c["x"]) ** 2 + (cy - c["y"]) ** 2) / max(r, 1)
        for c in callouts
    )


def draw_label(img, text, cx, cy, colour):
    """Draw a small white-background label above the circle centre."""
    (tw, th), baseline = cv2.getTextSize(text, FONT, FONT_SCALE, 1)
    tx = cx - tw // 2
    ty = cy - 6
    # background rectangle
    cv2.rectangle(img, (tx - 2, ty - th - 2), (tx + tw + 2, ty + baseline + 1),
                  COL_TEXT_BG, -1)
    cv2.putText(img, text, (tx, ty), FONT, FONT_SCALE, colour, 1, cv2.LINE_AA)


def main():
    # ── Load artifacts ─────────────────────────────────────────────────────────
    image = cv2.imread(str(DIAGRAM_PATH))
    if image is None:
        print(f"ERROR: cannot read {DIAGRAM_PATH}")
        sys.exit(1)

    h, w = image.shape[:2]
    border_top = int(h * 0.10)
    border_bot = int(h * 0.90)

    bom_rows          = json.loads(BOM_PATH.read_text())
    existing_callouts = json.loads(OCR_PATH.read_text())

    def normalise(ref):
        return str(ref).strip().lstrip("0") or "0"

    visible_refs = {normalise(r["ref_no"]) for r in bom_rows
                    if "NOT SHOWN" not in (r.get("description") or "").upper()}
    detected_refs = {normalise(c["number"]) for c in existing_callouts}
    missing_refs  = visible_refs - detected_refs - set(_STRATEGY_D_RECOVERED.keys())

    print(f"[info] Image: {w}x{h}px  |  border zone: y < {border_top} or y > {border_bot}")
    print(f"[info] Existing callouts: {sorted(detected_refs, key=lambda x: int(x) if x.isdigit() else 0)}")
    print(f"[info] Strategy D recovered: {list(_STRATEGY_D_RECOVERED.keys())}")
    print(f"[info] Still missing after D: {sorted(missing_refs, key=lambda x: int(x) if x.isdigit() else 0)}")

    # ── Re-run circle detection ────────────────────────────────────────────────
    sys.path.insert(0, str(Path(__file__).parent))
    from modules.image_preprocessor import preprocess
    from modules.circle_detector import detect_circles

    preprocessed = preprocess(image, debug=False)
    circles = detect_circles(preprocessed)
    print(f"\n[circles] {len(circles)} total detected\n")

    # ── Annotate image ─────────────────────────────────────────────────────────
    overlay = image.copy()

    rows = []
    for idx, c in enumerate(circles):
        cx, cy, r = c["x"], c["y"], c["radius"]
        cid = f"C{idx}"

        in_border = (cy < border_top or cy > border_bot)
        sd_ref    = _is_strategy_d(c)
        dist_ratio = _nearest_callout_dist_ratio(c, existing_callouts)
        is_resolved = dist_ratio <= _RESOLVED_PROXIMITY_RATIO

        if sd_ref:
            status  = f"STRATEGY_D (ref={sd_ref})"
            colour  = COL_STRATEGY_D
            lw      = 3
        elif is_resolved:
            # Find which callout it belongs to
            nearest_callout = min(existing_callouts,
                key=lambda cl: math.sqrt((cx-cl["x"])**2+(cy-cl["y"])**2))
            status  = f"RESOLVED (ref={nearest_callout['number']})"
            colour  = COL_RESOLVED
            lw      = 2
        elif in_border:
            status  = "BORDER_ZONE (unresolved)"
            colour  = COL_BORDER
            lw      = 1
        else:
            status  = "UNRESOLVED"
            colour  = COL_UNRESOLVED
            lw      = 3

        # Draw circle outline
        cv2.circle(overlay, (cx, cy), r, colour, lw)
        # Draw centre dot
        cv2.circle(overlay, (cx, cy), 3, colour, -1)

        # Label: CID + coords
        label_top  = f"{cid}"
        label_bot  = f"({cx},{cy})"
        draw_label(overlay, label_top, cx, cy - r - 2, colour)

        rows.append({
            "id": cid, "x": cx, "y": cy, "r": r,
            "in_border": in_border,
            "dist_ratio": round(dist_ratio, 2),
            "status": status,
        })

    # ── Legend ─────────────────────────────────────────────────────────────────
    legend = [
        (COL_RESOLVED,   "Resolved (callout detected)"),
        (COL_STRATEGY_D, "Recovered by Strategy D"),
        (COL_UNRESOLVED, "UNRESOLVED — candidate for missing refs"),
        (COL_BORDER,     "Border zone (unresolved, excluded)"),
    ]
    lx, ly = 20, 30
    for col, txt in legend:
        cv2.rectangle(overlay, (lx, ly - 12), (lx + 18, ly + 4), col, -1)
        cv2.putText(overlay, txt, (lx + 24, ly), FONT, 0.55, (0,0,0), 1, cv2.LINE_AA)
        ly += 24

    # ── Save ───────────────────────────────────────────────────────────────────
    cv2.imwrite(str(OUT_PATH), overlay)
    print(f"[output] Saved to {OUT_PATH}\n")

    # ── Print table ────────────────────────────────────────────────────────────
    print(f"{'ID':<5} {'x':>5} {'y':>5} {'r':>4} {'dist/r':>7} {'border':>7}  STATUS")
    print("-" * 80)
    for row in rows:
        border_flag = "YES" if row["in_border"] else ""
        print(f"{row['id']:<5} {row['x']:>5} {row['y']:>5} {row['r']:>4} "
              f"{row['dist_ratio']:>7.2f} {border_flag:>7}  {row['status']}")

    print(f"\n{'─'*60}")
    print(f"UNRESOLVED circles in valid zone (potential 4/9 candidates):")
    candidates = [r for r in rows if "UNRESOLVED" in r["status"] and not r["in_border"]]
    if candidates:
        for c in candidates:
            print(f"  {c['id']}  x={c['x']} y={c['y']} r={c['r']}")
    else:
        print("  NONE — the circle detector found NO unresolved circles in the valid zone")
        print("  (other than the one recovered as ref=8 by Strategy D)")
    print(f"{'─'*60}")

    print(f"\nAnswer to diagnostic questions:")
    print(f"  Missing refs after Strategy D: {sorted(missing_refs, key=lambda x: int(x) if x.isdigit() else 0)}")
    if candidates:
        print(f"  Candidate circles available for Strategy E to identify: {[c['id'] for c in candidates]}")
        print(f"  → Strategy E should receive these candidate coordinates + missing ref list")
    else:
        print(f"  NO candidate circles exist for missing refs")
        print(f"  → Strategy E must do a FULL DIAGRAM SEARCH for missing refs")


if __name__ == "__main__":
    main()
