"""
DocTR Strategy D Diagnostic
----------------------------
Standalone script — does NOT modify the pipeline.

Tests whether DocTR can recover missing callout refs that PaddleOCR missed,
using Assembly 1 (Running Gear Standard Axle) from the 10-page combined PDF.

Recovery targets are computed dynamically from the actual BOM and the
already-detected callout set — no hardcoded ref numbers.

Run from the ai-worker directory:
    venv/Scripts/python doctr_diagnostic.py
"""

import json
import math
import re
import sys
from pathlib import Path

import cv2
import numpy as np

# ── Paths ─────────────────────────────────────────────────────────────────────
JOB_DIR      = Path("../storage/outputs/e039a267-7cd3-472b-adaf-89a9074770b8")
ASSEMBLY_DIR = JOB_DIR / "assembly_1"
DIAGRAM_PATH = ASSEMBLY_DIR / "diagram.png"
BOM_PATH     = ASSEMBLY_DIR / "bom_raw.json"
OCR_PATH     = ASSEMBLY_DIR / "ocr_results.json"

# ── Config ────────────────────────────────────────────────────────────────────
DIGIT_RE          = re.compile(r"^\d{1,2}$")
BORDER_TOP_FRAC   = 0.10   # top 10% excluded (header area)
BORDER_BOT_FRAC   = 0.90   # bottom 10% excluded (footer area)
# For circled-callout documents: DocTR hit accepted only if within this many
# circle-radii of a detected circle centre. Set None to skip circle check.
CIRCLE_PROXIMITY_MULTIPLIER = 3.0

# ── Helpers ───────────────────────────────────────────────────────────────────

def is_not_shown(row: dict) -> bool:
    return "NOT SHOWN" in (row.get("description") or "").upper()

def normalise_ref(ref: str) -> str:
    return ref.strip().lstrip("0") or "0"

def load_recovery_targets() -> set[str]:
    bom_rows     = json.loads(BOM_PATH.read_text())
    already_seen = {normalise_ref(c["number"]) for c in json.loads(OCR_PATH.read_text())}
    visible_refs = {normalise_ref(r["ref_no"]) for r in bom_rows if not is_not_shown(r)}
    targets      = visible_refs - already_seen
    print(f"\n[targets] BOM visible refs : {sorted(visible_refs, key=int)}")
    print(f"[targets] Already detected : {sorted(already_seen, key=lambda x: int(x) if x.isdigit() else 0)}")
    print(f"[targets] Recovery targets : {sorted(targets, key=int)}")
    return targets

def detect_circles_from_image(image: np.ndarray) -> list[dict]:
    """Re-run circle detection on the diagram using the same pipeline logic."""
    sys.path.insert(0, str(Path(__file__).parent))
    from modules.image_preprocessor import preprocess
    from modules.circle_detector import detect_circles
    preprocessed = preprocess(image, debug=False)
    circles = detect_circles(preprocessed)
    print(f"\n[circles] Detected {len(circles)} candidate circle(s)")
    return circles

def nearest_circle(cx: int, cy: int, circles: list[dict]) -> tuple[float, dict | None]:
    """Return (distance/radius, circle) for the closest circle."""
    if not circles:
        return float("inf"), None
    best_ratio = float("inf")
    best_c     = None
    for c in circles:
        dist  = math.sqrt((cx - c["x"]) ** 2 + (cy - c["y"]) ** 2)
        ratio = dist / max(c["radius"], 1)
        if ratio < best_ratio:
            best_ratio = ratio
            best_c     = c
    return best_ratio, best_c

# ── Main diagnostic ───────────────────────────────────────────────────────────

def run():
    print("=" * 64)
    print("DocTR Strategy D Diagnostic")
    print("=" * 64)

    # 1. Load diagram
    image = cv2.imread(str(DIAGRAM_PATH))
    if image is None:
        print(f"ERROR: could not load {DIAGRAM_PATH}")
        sys.exit(1)
    h, w = image.shape[:2]
    print(f"\n[image] {DIAGRAM_PATH.name}  {w}x{h}px")

    border_top = int(h * BORDER_TOP_FRAC)
    border_bot = int(h * BORDER_BOT_FRAC)
    print(f"[image] Border exclusion zone: y < {border_top} or y > {border_bot}")

    # 2. Recovery targets
    targets = load_recovery_targets()
    if not targets:
        print("\n[result] No recovery targets — all BOM refs already detected. Exiting.")
        return

    # 3. Circle candidates
    circles = detect_circles_from_image(image)

    # 4. Run DocTR
    print("\n[doctr] Loading model...")
    try:
        from doctr.models import ocr_predictor
        from doctr.io import DocumentFile
    except ImportError as e:
        print(f"[doctr] IMPORT FAILED: {e}")
        return

    model = ocr_predictor(pretrained=True)
    print("[doctr] Model loaded. Running inference...")

    doc    = DocumentFile.from_images([str(DIAGRAM_PATH)])
    result = model(doc)

    # 5. Parse all DocTR detections
    print("\n[doctr] All digit detections on this page:")
    print(f"  {'text':>6}  {'conf':>5}  {'cx':>5}  {'cy':>5}  {'x0':>5}  {'y0':>5}  {'x1':>5}  {'y1':>5}  {'in_zone':>8}  {'near_circle':>12}  {'is_target':>10}")
    print("  " + "-" * 100)

    all_detections  = []
    recovery_hits   = []
    false_positives = []

    page = result.pages[0]
    for block in page.blocks:
        for line in block.lines:
            for word in line.words:
                text  = word.value.strip()
                conf  = round(word.confidence, 3)
                geo   = word.geometry           # ((x0,y0),(x1,y1)) normalized 0-1
                x0n, y0n = geo[0]
                x1n, y1n = geo[1]

                cx_px = int((x0n + x1n) / 2 * w)
                cy_px = int((y0n + y1n) / 2 * h)
                x0_px = int(x0n * w)
                y0_px = int(y0n * h)
                x1_px = int(x1n * w)
                y1_px = int(y1n * h)

                if not DIGIT_RE.match(text):
                    continue

                norm_text = text.lstrip("0") or "0"
                in_zone   = border_top <= cy_px <= border_bot
                circ_ratio, nearest = nearest_circle(cx_px, cy_px, circles)
                near_circle = circ_ratio <= CIRCLE_PROXIMITY_MULTIPLIER
                is_target   = norm_text in targets

                tag = ""
                if is_target and in_zone:
                    tag = "<<< RECOVERY CANDIDATE"
                elif not in_zone:
                    tag = "(border zone)"

                print(f"  {text:>6}  {conf:>5.3f}  {cx_px:>5}  {cy_px:>5}  "
                      f"{x0_px:>5}  {y0_px:>5}  {x1_px:>5}  {y1_px:>5}  "
                      f"{'YES' if in_zone else 'NO':>8}  "
                      f"{'YES' if near_circle else 'NO':>12}  "
                      f"{'YES' if is_target else 'NO':>10}  {tag}")

                entry = {
                    "text": text, "norm": norm_text, "conf": conf,
                    "cx": cx_px, "cy": cy_px,
                    "x0": x0_px, "y0": y0_px, "x1": x1_px, "y1": y1_px,
                    "in_zone": in_zone, "near_circle": near_circle,
                    "circ_ratio": round(circ_ratio, 2), "is_target": is_target,
                }
                all_detections.append(entry)
                if is_target and in_zone:
                    recovery_hits.append(entry)
                elif not is_target and in_zone and norm_text.isdigit():
                    false_positives.append(entry)

    # 6. Recovery summary
    print(f"\n{'=' * 64}")
    print("RECOVERY SUMMARY")
    print(f"{'=' * 64}")
    recovered_targets = {h["norm"] for h in recovery_hits}
    still_missing     = targets - recovered_targets

    print(f"\nTargets    : {sorted(targets, key=int)}")
    print(f"Recovered  : {sorted(recovered_targets, key=int)}")
    print(f"Still missing: {sorted(still_missing, key=int) if still_missing else 'none'}")

    if recovery_hits:
        print("\nRecovery candidates detail:")
        for h in recovery_hits:
            radius = max(h["x1"] - h["x0"], h["y1"] - h["y0"]) // 2
            print(f"  ref={h['text']}  conf={h['conf']:.3f}  "
                  f"x={h['cx']} y={h['cy']} radius~{radius}  "
                  f"near_circle={h['near_circle']} (ratio={h['circ_ratio']})")
            print(f"    → hotspot dict: {{number: \"{h['norm']}\", x: {h['cx']}, "
                  f"y: {h['cy']}, radius: {radius}, extractionMethod: \"doctr\"}}")

    # 7. False positives check
    print(f"\nFalse positive numeric detections (in zone, not a target):")
    if false_positives:
        for fp in false_positives:
            print(f"  text={fp['text']}  conf={fp['conf']:.3f}  "
                  f"cx={fp['cx']} cy={fp['cy']}  near_circle={fp['near_circle']}")
    else:
        print("  none")

    print(f"\n{'=' * 64}")
    verdict = "PROCEED with DocTR integration" if recovery_hits else "DocTR did NOT recover targets — reconsider"
    print(f"VERDICT: {verdict}")
    print(f"{'=' * 64}\n")


if __name__ == "__main__":
    run()
