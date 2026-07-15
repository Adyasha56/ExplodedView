"""
LLM Resolver — Gemini 2.5 Flash via REST API.

Validates fuzzy mappings and flags consistency issues using BOM text context.
Uses requests (not google-generativeai) to avoid the protobuf conflict with paddlepaddle.

Contract: never reads callout positions from the image, never invents coordinates,
never overrides exact matches. Returns mapping_result unchanged on any failure.
"""

import json
import time

import requests

from config import GEMINI_API_KEY, GEMINI_MODEL, LLM_TIMEOUT_SECONDS
from utils.logger import get_logger

logger = get_logger("llm_resolver")

_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models"
    "/{model}:generateContent?key={key}"
)


def resolve_with_llm(
    mapping_result: dict,
    bom_rows: list[dict],
) -> dict:
    """
    Validate fuzzy mappings and detect consistency issues using Gemini 2.5 Flash.

    Returns mapping_result with 'llm_validations' key added.
    On any failure, llm_validations is [] and the rest is unchanged.
    """
    fuzzy = [m for m in mapping_result["mappings"] if m["confidence"] < 1.0]

    if not fuzzy and not mapping_result.get("unmapped_hotspots"):
        logger.info("llm_resolver: no fuzzy mappings or unmapped hotspots — skipping")
        return {**mapping_result, "llm_validations": []}

    if not GEMINI_API_KEY:
        logger.warning("llm_resolver: GEMINI_API_KEY not set — skipping LLM call")
        return {**mapping_result, "llm_validations": []}

    logger.info(
        "llm_resolver: calling Gemini — %d fuzzy mapping(s), %d unmapped hotspot(s)",
        len(fuzzy), len(mapping_result.get("unmapped_hotspots", [])),
    )

    t_start = time.perf_counter()
    try:
        validations = _call_gemini(mapping_result, bom_rows)
        elapsed = (time.perf_counter() - t_start) * 1000
        logger.info("llm_resolver: %d validation(s) in %.0f ms", len(validations), elapsed)
        return {**mapping_result, "llm_validations": validations}

    except Exception as exc:
        elapsed = (time.perf_counter() - t_start) * 1000
        logger.warning(
            "llm_resolver: LLM call failed after %.0f ms (%s) — "
            "returning deterministic results unchanged",
            elapsed, exc,
        )
        return {**mapping_result, "llm_validations": []}


# ── Gemini REST call ──────────────────────────────────────────────────────────

def _call_gemini(mapping_result: dict, bom_rows: list[dict]) -> list[dict]:
    prompt = _build_prompt(
        confirmed_mappings=[m for m in mapping_result["mappings"] if m["confidence"] >= 1.0],
        fuzzy_mappings=[m for m in mapping_result["mappings"] if m["confidence"] < 1.0],
        unmapped_hotspots=mapping_result.get("unmapped_hotspots", []),
        unpositioned_bom_rows=mapping_result.get("unpositioned_bom_rows", []),
        bom_rows=bom_rows,
    )

    url = _GEMINI_URL.format(model=GEMINI_MODEL, key=GEMINI_API_KEY)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }

    response = requests.post(url, json=payload, timeout=LLM_TIMEOUT_SECONDS)
    response.raise_for_status()

    data = response.json()
    raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    parsed = json.loads(raw_text)

    return _extract_validations(parsed)


def _build_prompt(
    confirmed_mappings: list[dict],
    fuzzy_mappings: list[dict],
    unmapped_hotspots: list[dict],
    unpositioned_bom_rows: list[dict],
    bom_rows: list[dict],
) -> str:
    confirmed_slim = [
        {"hotspotNumber": m["hotspot_number"],
         "bom": [{"refNo": r["ref_no"], "description": r.get("description")}
                 for r in m["bom"]]}
        for m in confirmed_mappings
    ]
    fuzzy_slim = [
        {"hotspotNumber": m["hotspot_number"],
         "confidence": m["confidence"],
         "bom": [{"refNo": r["ref_no"], "description": r.get("description")}
                 for r in m["bom"]]}
        for m in fuzzy_mappings
    ]
    unpositioned_slim = [
        {"refNo": r["ref_no"], "partNo": r.get("part_no"), "description": r.get("description")}
        for r in unpositioned_bom_rows
    ]
    bom_slim = [
        {"refNo": r["ref_no"], "partNo": r.get("part_no"),
         "description": r.get("description"), "qty": r.get("qty")}
        for r in bom_rows
    ]

    return f"""You are validating hotspot-to-BOM mappings extracted from an engineering exploded-view diagram.

CONFIRMED EXACT MAPPINGS (do not modify):
{json.dumps(confirmed_slim, indent=2)}

FUZZY MAPPINGS REQUIRING VALIDATION (confidence < 1.0):
{json.dumps(fuzzy_slim, indent=2)}

UNMAPPED HOTSPOTS (detected on diagram but no BOM match found):
{json.dumps([h["number"] for h in unmapped_hotspots], indent=2)}

UNPOSITIONED BOM ROWS (exist in BOM but callout not detected on diagram — do NOT invent coordinates):
{json.dumps(unpositioned_slim, indent=2)}

FULL BOM FOR CONTEXT:
{json.dumps(bom_slim, indent=2)}

INSTRUCTIONS:
1. For each fuzzy mapping, validate whether the hotspot and BOM reference are a correct match based on part descriptions and BOM context.
2. Flag consistency issues across all mappings (assembly references, mismatched descriptions, etc.).
3. Do NOT invent coordinates for unpositioned BOM rows.
4. Do NOT modify confirmed exact mappings.
5. For unmapped hotspots, suggest a likely BOM ref only if evidence is strong; mark as low confidence.

Respond ONLY with valid JSON matching this exact schema — no prose, no markdown fences:
{{
  "fuzzy_validations": [
    {{
      "hotspot_number": "string",
      "ref_no": "string",
      "verdict": "confirmed | rejected | uncertain",
      "confidence": 0.0,
      "reason": "string"
    }}
  ],
  "hotspot_suggestions": [
    {{
      "hotspot_number": "string",
      "suggested_ref_no": "string",
      "confidence": 0.0,
      "reason": "string"
    }}
  ],
  "consistency_flags": [
    {{
      "ref_no": "string",
      "flag": "string",
      "severity": "info | warning | error"
    }}
  ]
}}"""


def _extract_validations(parsed: dict) -> list[dict]:
    """Flatten and validate LLM response fields. Drops malformed entries silently."""
    validations = []

    for v in parsed.get("fuzzy_validations", []):
        if all(k in v for k in ("hotspot_number", "ref_no", "verdict", "confidence", "reason")):
            validations.append({"type": "fuzzy_validation", **v})

    for s in parsed.get("hotspot_suggestions", []):
        if all(k in s for k in ("hotspot_number", "suggested_ref_no", "confidence", "reason")):
            validations.append({"type": "hotspot_suggestion", **s})

    for f in parsed.get("consistency_flags", []):
        if all(k in f for k in ("ref_no", "flag", "severity")):
            validations.append({"type": "consistency_flag", **f})

    return validations
