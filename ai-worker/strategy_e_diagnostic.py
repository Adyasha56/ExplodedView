"""
Strategy E Diagnostic
---------------------
Standalone test of Gemini Vision recovery against existing job artifacts.
Does NOT re-run the full pipeline — uses saved diagram.png, bom_raw.json,
and ocr_results.json from a previous run.

Also simulates the full A→D→E callout state by merging Strategy D's known
recovery (ref=8) into the existing_callouts before calling Strategy E, so E
only sees refs 4 and 9 as missing.

Run from the ai-worker directory:
    venv/Scripts/python strategy_e_diagnostic.py
"""

import json
import logging
import sys
from pathlib import Path

import cv2

# ── Paths ──────────────────────────────────────────────────────────────────────
JOB_DIR      = Path("../storage/outputs/e039a267-7cd3-472b-adaf-89a9074770b8")
ASSEMBLY_DIR = JOB_DIR / "assembly_1"
DIAGRAM_PATH = ASSEMBLY_DIR / "diagram.png"
BOM_PATH     = ASSEMBLY_DIR / "bom_raw.json"
OCR_PATH     = ASSEMBLY_DIR / "ocr_results.json"

# Strategy D result (from previous diagnostic run)
STRATEGY_D_CALLOUT = {
    "x": 1208, "y": 2165, "radius": 22,
    "number": "8", "extraction_method": "paddleocr_enhanced", "score": 0.705,
}


def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    print("=" * 64)
    print("Strategy E Diagnostic — Gemini Vision Targeted Recovery")
    print("=" * 64)

    # ── Load artifacts ─────────────────────────────────────────────────────────
    image = cv2.imread(str(DIAGRAM_PATH))
    if image is None:
        print(f"ERROR: cannot read {DIAGRAM_PATH}")
        sys.exit(1)
    h, w = image.shape[:2]
    print(f"\n[image]   {w}x{h}px")

    bom_rows          = json.loads(BOM_PATH.read_text())
    existing_callouts = json.loads(OCR_PATH.read_text())

    # Merge Strategy D result so E only sees [4, 9] as missing
    existing_callouts_with_d = existing_callouts + [STRATEGY_D_CALLOUT]

    existing_nums = sorted(c["number"] for c in existing_callouts_with_d)
    print(f"[callouts] After A+B+C+D: {existing_nums}")

    # ── Re-run circle detection ────────────────────────────────────────────────
    sys.path.insert(0, str(Path(__file__).parent))
    from modules.image_preprocessor import preprocess
    from modules.circle_detector import detect_circles

    preprocessed = preprocess(image, debug=False)
    circles       = detect_circles(preprocessed)
    print(f"[circles]  {len(circles)} detected")

    # ── Show what Strategy E will receive ─────────────────────────────────────
    from modules.strategy_e_recovery import (
        _compute_missing_refs,
        _find_unresolved_circles,
    )

    missing = _compute_missing_refs(bom_rows, existing_callouts_with_d)
    border_top = int(h * 0.10)
    border_bot = int(h * 0.90)
    unresolved = _find_unresolved_circles(circles, existing_callouts_with_d, border_top, border_bot)

    print(f"\n[strategy_e input]")
    print(f"  Missing refs  : {sorted(missing, key=lambda x: int(x) if x.isdigit() else 0)}")
    print(f"  Candidates    :")
    for i, c in enumerate(unresolved):
        print(f"    C{i}  x={c['x']} y={c['y']} r={c['radius']}")

    # ── Run Strategy E ─────────────────────────────────────────────────────────
    print(f"\n{'=' * 64}")
    print("CALLING GEMINI VISION")
    print(f"{'=' * 64}\n")

    from modules.strategy_e_recovery import recover_with_gemini
    recovered = recover_with_gemini(
        diagram_image=image,
        circles=circles,
        existing_callouts=existing_callouts_with_d,
        bom_rows=bom_rows,
    )

    # ── Final state ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 64}")
    print("STRATEGY E RESULTS")
    print(f"{'=' * 64}")

    recovered_refs = {r["number"] for r in recovered}
    still_missing  = missing - recovered_refs

    print(f"  Recovered : {sorted(recovered_refs, key=lambda x: int(x) if x.isdigit() else 0)}")
    print(f"  Still missing after ALL strategies: "
          f"{sorted(still_missing, key=lambda x: int(x) if x.isdigit() else 0) if still_missing else 'none'}")

    if recovered:
        print("\n  Detail:")
        for r in recovered:
            print(f"    ref={r['number']}  conf={r['score']:.3f}  "
                  f"x={r['x']} y={r['y']} r={r['radius']}  method={r['extraction_method']}")

    # ── Simulate final callout list + mapping summary ──────────────────────────
    final_callouts = existing_callouts_with_d + recovered
    final_refs     = sorted({c["number"] for c in final_callouts},
                            key=lambda x: int(x) if x.isdigit() else 0)

    print(f"\n{'=' * 64}")
    print("FINAL CALLOUT LIST (A+B+C+D+E)")
    print(f"{'=' * 64}")
    print(f"  {final_refs}")

    if not still_missing:
        verdict = "FULL RECOVERY — all BOM visible refs now positioned"
    elif recovered_refs:
        verdict = f"PARTIAL RECOVERY — {len(still_missing)} ref(s) remain unpositioned"
    else:
        verdict = "NO RECOVERY — Strategy E did not recover any targets"

    print(f"\n{'=' * 64}")
    print(f"VERDICT: {verdict}")
    print(f"{'=' * 64}\n")


if __name__ == "__main__":
    main()
