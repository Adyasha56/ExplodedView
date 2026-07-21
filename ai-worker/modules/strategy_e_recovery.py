"""
Strategy E — Gemini Vision Targeted Recovery

After Strategies A/B/C/D, some BOM refs may still have unresolved circle
candidates (circles the detector found, but PaddleOCR returned nothing for).

This module sends the full diagram image to Gemini Vision alongside:
  - The unresolved candidate circle list (with pixel coordinates)
  - The still-missing BOM refs and their part metadata

Gemini identifies which candidate circle contains which ref number.
The circle's existing centre/radius from the detector is always used as
canonical coordinates — Gemini never generates new coordinates.

CANDIDATE MODE ONLY: if no unresolved circles exist, this module returns
immediately. Full-diagram coordinate search is not implemented here.

Gemini failure (network error, bad API key, malformed response) is fully
graceful: logs a warning and returns an empty list, so the rest of the
pipeline is unaffected.
"""

import base64
import json
import math
import time

import cv2
import numpy as np

from config import GEMINI_API_KEY, GEMINI_MODEL, LLM_TIMEOUT_SECONDS
from utils.gemini_http import gemini_post
from utils.logger import get_logger

logger = get_logger("strategy_e")

# Minimum Gemini-reported confidence to accept a candidate match.
_MIN_GEMINI_CONFIDENCE = 0.70

# A circle is "resolved" if an existing callout lies within this many radii.
# Must match strategy_d_recovery._RESOLVED_PROXIMITY_RATIO.
_RESOLVED_PROXIMITY_RATIO = 1.5

_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models"
    "/{model}:generateContent?key={key}"
)


# ── Public entry point ─────────────────────────────────────────────────────────

def recover_with_gemini(
    diagram_image: np.ndarray,
    circles: list[dict],
    existing_callouts: list[dict],
    bom_rows: list[dict],
) -> list[dict]:
    """
    Returns a list of recovered callout dicts (same schema as callout_reader output).

    Only runs when:
      - GEMINI_API_KEY is set
      - There are still-missing BOM refs after Strategies A-D
      - At least one unresolved candidate circle exists in the valid zone

    Never raises — all failures return [].
    """
    if not GEMINI_API_KEY:
        logger.warning("Strategy E: GEMINI_API_KEY not set — skipping")
        return []

    missing_refs = _compute_missing_refs(bom_rows, existing_callouts)
    if not missing_refs:
        logger.info("Strategy E: no missing refs after Strategies A-D — skipping")
        return []

    h, w = diagram_image.shape[:2]
    border_top = int(h * 0.03)
    border_bot = int(h * 0.97)
    unresolved = _find_unresolved_circles(circles, existing_callouts, border_top, border_bot)

    if not unresolved:
        logger.info(
            "Strategy E: %d ref(s) still missing but NO unresolved circle candidates — "
            "refs will remain unpositioned: %s",
            len(missing_refs),
            sorted(missing_refs, key=lambda x: int(x) if x.isdigit() else 0),
        )
        return []

    logger.info(
        "Strategy E: %d missing ref(s) %s — %d unresolved candidate circle(s): %s",
        len(missing_refs),
        sorted(missing_refs, key=lambda x: int(x) if x.isdigit() else 0),
        len(unresolved),
        [(f"C{i}", c["x"], c["y"]) for i, c in enumerate(unresolved)],
    )

    t_start = time.perf_counter()
    try:
        recovered = _call_gemini(diagram_image, unresolved, missing_refs, bom_rows, existing_callouts)
        elapsed   = (time.perf_counter() - t_start) * 1000
        logger.info(
            "Strategy E: Gemini call complete in %.0f ms — recovered %d ref(s): %s",
            elapsed, len(recovered), [r["number"] for r in recovered],
        )
        still_missing = missing_refs - {r["number"] for r in recovered}
        if still_missing:
            logger.info(
                "Strategy E: %d ref(s) remain unpositioned after all strategies: %s",
                len(still_missing),
                sorted(still_missing, key=lambda x: int(x) if x.isdigit() else 0),
            )
        return recovered

    except Exception as exc:
        elapsed = (time.perf_counter() - t_start) * 1000
        logger.warning(
            "Strategy E: Gemini call FAILED after %.0f ms (%s) — "
            "missing refs will remain unpositioned: %s",
            elapsed, exc,
            sorted(missing_refs, key=lambda x: int(x) if x.isdigit() else 0),
        )
        return []


# ── Core Gemini call ───────────────────────────────────────────────────────────

def _call_gemini(
    diagram_image: np.ndarray,
    unresolved: list[dict],
    missing_refs: set[str],
    bom_rows: list[dict],
    existing_callouts: list[dict],
) -> list[dict]:
    image_b64 = _encode_image(diagram_image)
    prompt     = _build_prompt(unresolved, missing_refs, bom_rows, existing_callouts)

    url = _GEMINI_URL.format(model=GEMINI_MODEL, key=GEMINI_API_KEY)
    payload = {
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": "image/png", "data": image_b64}},
                {"text": prompt},
            ]
        }],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }

    logger.info("Strategy E: sending multimodal request to Gemini (%s)", GEMINI_MODEL)
    response = gemini_post(url, payload, timeout=max(LLM_TIMEOUT_SECONDS, 120), logger=logger)

    data     = response.json()
    raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    logger.debug("Strategy E: Gemini raw response:\n%s", raw_text)

    parsed = json.loads(raw_text)
    return _extract_recoveries(parsed, unresolved, missing_refs)


def _build_prompt(
    unresolved: list[dict],
    missing_refs: set[str],
    bom_rows: list[dict],
    existing_callouts: list[dict],
) -> str:
    # Build metadata for each missing ref from the BOM
    bom_lookup = {_normalise(r["ref_no"]): r for r in bom_rows}
    missing_meta = []
    for ref in sorted(missing_refs, key=lambda x: int(x) if x.isdigit() else 0):
        row = bom_lookup.get(ref, {})
        missing_meta.append({
            "ref_no":      ref,
            "part_no":     row.get("part_no", ""),
            "description": row.get("description", ""),
            "qty":         row.get("qty", ""),
        })

    # Already-resolved hotspots (for spatial context)
    resolved_context = [
        {"ref_no": c["number"], "x": c["x"], "y": c["y"]}
        for c in existing_callouts
    ]

    # Candidate circles with IDs
    candidates = [
        {"id": f"C{i}", "x": c["x"], "y": c["y"], "radius": c["radius"]}
        for i, c in enumerate(unresolved)
    ]

    return f"""You are analyzing an engineering exploded-view diagram.

The diagram shows numbered callouts (circled numbers) that identify individual parts.
I have detected circles on the diagram using computer vision, but OCR failed to read
the numbers inside some of them.

IMAGE: The attached image is the full high-resolution diagram (pixel coordinates
are measured from top-left, x=rightward, y=downward).

ALREADY RESOLVED CALLOUTS (for spatial context):
{json.dumps(resolved_context, indent=2)}

UNRESOLVED CIRCLE CANDIDATES (OCR failed on these — examine the image carefully):
{json.dumps(candidates, indent=2)}

MISSING BOM REFS (these ref numbers exist in the parts list but could not be read):
{json.dumps(missing_meta, indent=2)}

TASK:
For each missing ref number in MISSING BOM REFS, examine the UNRESOLVED CIRCLE
CANDIDATES in the image. Look at the pixel coordinates given — find that circle
in the image and read the number printed inside it.

Rules:
- Only match a ref to a candidate if you can clearly see that number inside the circle.
- Each candidate can match at most one ref. Each ref can match at most one candidate.
- If you cannot confidently identify a match, set "candidate_id" to null.
- Do NOT invent coordinates. Only use the candidate IDs provided.
- Confidence must reflect how clearly you can read the number in the image (0.0–1.0).

Respond ONLY with valid JSON — no prose, no markdown fences:
{{
  "identifications": [
    {{
      "ref_no": "string",
      "candidate_id": "C0" | null,
      "confidence": 0.0,
      "reasoning": "string"
    }}
  ]
}}"""


def _extract_recoveries(
    parsed: dict,
    unresolved: list[dict],
    missing_refs: set[str],
) -> list[dict]:
    """Map Gemini's identifications back to circle geometry."""
    candidate_map = {f"C{i}": c for i, c in enumerate(unresolved)}
    used_candidates: set[str] = set()
    recovered: list[dict] = []

    for identification in parsed.get("identifications", []):
        ref         = str(identification.get("ref_no", "")).strip().lstrip("0") or "0"
        cid         = identification.get("candidate_id")
        confidence  = float(identification.get("confidence", 0.0))
        reasoning   = identification.get("reasoning", "")

        if ref not in missing_refs:
            logger.debug("Strategy E: ignoring ref=%s — not in missing set", ref)
            continue

        if cid is None:
            logger.info(
                "Strategy E: ref=%s — Gemini returned no match (conf=%.2f): %s",
                ref, confidence, reasoning,
            )
            continue

        if cid in used_candidates:
            logger.warning("Strategy E: ref=%s — candidate %s already claimed, skipping", ref, cid)
            continue

        if cid not in candidate_map:
            logger.warning("Strategy E: ref=%s — unknown candidate_id '%s', skipping", ref, cid)
            continue

        if confidence < _MIN_GEMINI_CONFIDENCE:
            logger.info(
                "Strategy E: ref=%s — confidence %.2f < %.2f threshold via %s — keeping unpositioned",
                ref, confidence, _MIN_GEMINI_CONFIDENCE, cid,
            )
            continue

        circle = candidate_map[cid]
        used_candidates.add(cid)
        entry = {
            "x":                 circle["x"],
            "y":                 circle["y"],
            "radius":            circle["radius"],
            "number":            ref,
            "extraction_method": "gemini_vision",
            "score":             round(confidence, 3),
        }
        recovered.append(entry)
        logger.info(
            "Strategy E: ref=%s -> %s (x=%d, y=%d, r=%d) conf=%.2f - %s",
            ref, cid, circle["x"], circle["y"], circle["radius"],
            confidence, reasoning,
        )

    return recovered


# ── Helpers ────────────────────────────────────────────────────────────────────

def _compute_missing_refs(bom_rows: list[dict], existing_callouts: list[dict]) -> set[str]:
    def is_not_shown(row: dict) -> bool:
        return "NOT SHOWN" in (row.get("description") or "").upper()

    visible  = {_normalise(r["ref_no"]) for r in bom_rows if not is_not_shown(r)}
    detected = {_normalise(c["number"]) for c in existing_callouts}
    return visible - detected


def _find_unresolved_circles(
    circles: list[dict],
    existing_callouts: list[dict],
    border_top: int,
    border_bot: int,
) -> list[dict]:
    unresolved = []
    for circle in circles:
        cx, cy, r = circle["x"], circle["y"], circle["radius"]
        if cy < border_top or cy > border_bot:
            continue
        near = any(
            math.sqrt((cx - c["x"]) ** 2 + (cy - c["y"]) ** 2) <= r * _RESOLVED_PROXIMITY_RATIO
            for c in existing_callouts
        )
        if not near:
            unresolved.append(circle)
    return unresolved


def _normalise(ref) -> str:
    return str(ref).strip().lstrip("0") or "0"


def _encode_image(image: np.ndarray) -> str:
    """Encode numpy image array to base64 PNG string for Gemini inline_data.

    Resizes to max 1500px on the longest side before encoding. Callout circle
    numbers remain legible at this resolution and the smaller payload reduces
    network transfer time, avoiding read timeouts on hosted deployments.
    """
    h, w = image.shape[:2]
    max_dim = 1500
    if max(h, w) > max_dim:
        scale = max_dim / max(h, w)
        new_w = int(w * scale)
        new_h = int(h * scale)
        image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
        logger.info(
            "_encode_image: resized %dx%d -> %dx%d for Gemini payload",
            w, h, new_w, new_h,
        )
    success, buf = cv2.imencode(".png", image)
    if not success:
        raise RuntimeError("Failed to encode diagram image as PNG")
    return base64.b64encode(buf.tobytes()).decode("utf-8")
