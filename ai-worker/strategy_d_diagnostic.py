"""
Strategy D Diagnostic
---------------------
Standalone script — does NOT modify the pipeline or any stored files.

Tests Strategy D (enhanced unresolved-circle PaddleOCR recovery) against
existing pipeline artifacts for a specific job/assembly without re-running
the full pipeline.

Run from the ai-worker directory:
    venv/Scripts/python strategy_d_diagnostic.py
"""

import json
import sys
from pathlib import Path

import cv2

# ── Paths — edit these to point at your job artifacts ─────────────────────────
JOB_DIR      = Path("../storage/outputs/e039a267-7cd3-472b-adaf-89a9074770b8")
ASSEMBLY_DIR = JOB_DIR / "assembly_1"
DIAGRAM_PATH = ASSEMBLY_DIR / "diagram.png"
BOM_PATH     = ASSEMBLY_DIR / "bom_raw.json"
OCR_PATH     = ASSEMBLY_DIR / "ocr_results.json"


def main():
    print("=" * 64)
    print("Strategy D Diagnostic")
    print("=" * 64)

    # ── Load artifacts ─────────────────────────────────────────────────────────
    image = cv2.imread(str(DIAGRAM_PATH))
    if image is None:
        print(f"ERROR: could not read {DIAGRAM_PATH}")
        sys.exit(1)
    h, w = image.shape[:2]
    print(f"\n[image] {DIAGRAM_PATH.name}  {w}x{h}px")

    bom_rows         = json.loads(BOM_PATH.read_text())
    existing_callouts = json.loads(OCR_PATH.read_text())
    print(f"[bom]   {len(bom_rows)} rows")
    print(f"[ocr]   {len(existing_callouts)} existing callout(s): "
          f"{sorted(c['number'] for c in existing_callouts)}")

    # ── Re-run circle detection ────────────────────────────────────────────────
    sys.path.insert(0, str(Path(__file__).parent))
    from modules.image_preprocessor import preprocess
    from modules.circle_detector import detect_circles

    preprocessed = preprocess(image, debug=False)
    circles = detect_circles(preprocessed)
    print(f"[circles] {len(circles)} candidate circle(s)")

    # ── Patch strategy_d_recovery to emit verbose per-variant logs ─────────────
    import logging
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s  %(name)s  %(message)s")

    # ── Run Strategy D ─────────────────────────────────────────────────────────
    from modules.strategy_d_recovery import (
        recover_unresolved_circles,
        _compute_recovery_targets,
        _find_unresolved_circles,
    )

    targets    = _compute_recovery_targets(bom_rows, existing_callouts)
    unresolved = _find_unresolved_circles(circles, existing_callouts)

    print(f"\n{'=' * 64}")
    print("PRE-STRATEGY-D STATE")
    print(f"{'=' * 64}")

    def _norm(ref):
        return str(ref).strip().lstrip("0") or "0"

    visible = {_norm(r["ref_no"]) for r in bom_rows
               if "NOT SHOWN" not in (r.get("description") or "").upper()}
    detected = {_norm(c["number"]) for c in existing_callouts}

    print(f"  BOM visible refs   : {sorted(visible, key=lambda x: int(x) if x.isdigit() else 0)}")
    print(f"  Already detected   : {sorted(detected, key=lambda x: int(x) if x.isdigit() else 0)}")
    print(f"  Recovery targets   : {sorted(targets, key=lambda x: int(x) if x.isdigit() else 0)}")
    print(f"  Total circles      : {len(circles)}")
    print(f"  Unresolved circles : {len(unresolved)}")
    for i, c in enumerate(unresolved):
        print(f"    #{i}  x={c['x']} y={c['y']} r={c['radius']}")

    print(f"\n{'=' * 64}")
    print("RUNNING STRATEGY D")
    print(f"{'=' * 64}\n")

    recovered = recover_unresolved_circles(
        diagram_image=image,
        circles=circles,
        existing_callouts=existing_callouts,
        bom_rows=bom_rows,
    )

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{'=' * 64}")
    print("STRATEGY D RESULTS")
    print(f"{'=' * 64}")
    recovered_refs  = {r["number"] for r in recovered}
    still_missing   = targets - recovered_refs

    print(f"  Recovered refs  : {sorted(recovered_refs, key=lambda x: int(x) if x.isdigit() else 0)}")
    print(f"  Still missing   : {sorted(still_missing, key=lambda x: int(x) if x.isdigit() else 0) if still_missing else 'none'}")

    if recovered:
        print("\n  Detail:")
        for r in recovered:
            print(f"    ref={r['number']}  conf={r['score']:.3f}  votes={r.get('_votes','?')}  "
                  f"x={r['x']} y={r['y']} r={r['radius']}  method={r['extraction_method']}")

    if not still_missing:
        verdict = "FULL RECOVERY — all targets found by Strategy D"
    elif recovered_refs:
        verdict = f"PARTIAL RECOVERY — {len(still_missing)} target(s) still missing"
    else:
        verdict = "NO RECOVERY — Strategy D did not recover any targets"

    print(f"\n{'=' * 64}")
    print(f"VERDICT: {verdict}")
    print(f"{'=' * 64}\n")


if __name__ == "__main__":
    main()
