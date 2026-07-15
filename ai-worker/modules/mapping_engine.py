"""
Mapping Engine

Joins detected callout numbers to BOM ref numbers using a
three-stage deterministic pipeline:

  Stage 1 — Normalise both sides (strip leading zeros, strip whitespace)
  Stage 2 — Exact match
             For duplicate BOM refs (e.g. ref 11 appears twice), ALL matching
             rows are claimed and placed in a single mapping's bom[] array.
             One hotspot always produces exactly one mapping object.
  Stage 3 — Fuzzy match (Levenshtein edit distance <= MAPPING_MAX_EDIT_DISTANCE)
             Only the single best unclaimed row is claimed per hotspot.

Output keys:
  mappings              — one entry per detected hotspot; bom[] is always an array
  unmapped_hotspots     — hotspots with no BOM match (exact or fuzzy)
  unpositioned_bom_rows — BOM rows not claimed by any hotspot (OCR never found
                          the corresponding callout on the diagram)
"""

import time

from Levenshtein import distance as levenshtein_distance

from config import (
    MAPPING_CONFIDENCE_EXACT,
    MAPPING_CONFIDENCE_FUZZY,
    MAPPING_MAX_EDIT_DISTANCE,
)
from utils.logger import get_logger

logger = get_logger("mapping_engine")


def map_hotspots_to_bom(
    callouts: list[dict],
    bom_rows: list[dict],
) -> dict:
    """Returns { mappings, unmapped_hotspots, unpositioned_bom_rows }."""
    t_start = time.perf_counter()
    logger.info(
        "map_hotspots_to_bom: %d callout(s), %d BOM row(s)",
        len(callouts), len(bom_rows),
    )

    norm_callouts = [_normalise_callout(c) for c in callouts]
    norm_bom: list[tuple[str, dict]] = [
        (_normalise_ref(row["ref_no"]), row) for row in bom_rows
    ]

    mappings:            list[dict] = []
    unmapped_hotspots:   list[dict] = []
    claimed_bom_indices: set[int]   = set()

    for callout, norm_c in zip(callouts, norm_callouts):
        match_indices, confidence = _find_all_matches(norm_c, norm_bom, claimed_bom_indices)

        if match_indices:
            for idx in match_indices:
                claimed_bom_indices.add(idx)
            mappings.append({
                "hotspot_number": callout["number"],
                "x":              callout["x"],
                "y":              callout["y"],
                "radius":         callout["radius"],
                "confidence":     confidence,
                "bom":            [bom_rows[i] for i in match_indices],
            })
            logger.debug(
                "  callout #%s -> %d BOM row(s) [refs: %s] (confidence=%.2f)",
                callout["number"],
                len(match_indices),
                [bom_rows[i]["ref_no"] for i in match_indices],
                confidence,
            )
        else:
            unmapped_hotspots.append({
                "number":           callout["number"],
                "x":                callout["x"],
                "y":                callout["y"],
                "radius":           callout["radius"],
                "extraction_method": callout["extraction_method"],
            })
            logger.debug("  callout #%s -> no BOM match", callout["number"])

    unpositioned_bom_rows = [
        bom_rows[i] for i in range(len(bom_rows)) if i not in claimed_bom_indices
    ]

    elapsed = (time.perf_counter() - t_start) * 1000
    logger.info(
        "map_hotspots_to_bom complete in %.1f ms — "
        "%d mapped, %d unmapped hotspots, %d unpositioned BOM rows",
        elapsed, len(mappings), len(unmapped_hotspots), len(unpositioned_bom_rows),
    )

    if unmapped_hotspots:
        logger.info("  unmapped hotspots: %s", [h["number"] for h in unmapped_hotspots])
    if unpositioned_bom_rows:
        logger.info("  unpositioned BOM rows: %s", [r["ref_no"] for r in unpositioned_bom_rows])

    return {
        "mappings":              mappings,
        "unmapped_hotspots":     unmapped_hotspots,
        "unpositioned_bom_rows": unpositioned_bom_rows,
    }


# ── Match logic ────────────────────────────────────────────────────────────────

def _find_all_matches(
    norm_callout: str,
    norm_bom: list[tuple[str, dict]],
    already_claimed: set[int],
) -> tuple[list[int], float]:
    """
    Find all BOM rows for a normalised callout number.

    Exact path: returns ALL unclaimed rows whose ref equals the callout.
    Fuzzy path: returns the single best unclaimed row within edit distance
                threshold. Multi-row fuzzy claiming is unsound.

    Returns (list_of_bom_indices, confidence) or ([], 0.0) if no match.
    """
    # Stage 2 — Exact match: claim every unclaimed row sharing this ref
    exact_indices = [
        i for i, (ref, _) in enumerate(norm_bom)
        if i not in already_claimed and norm_callout == ref
    ]
    if exact_indices:
        return exact_indices, MAPPING_CONFIDENCE_EXACT

    # Stage 3 — Fuzzy match: single best unclaimed row
    best_idx:  int | None = None
    best_dist: int        = MAPPING_MAX_EDIT_DISTANCE + 1

    for i, (ref, _) in enumerate(norm_bom):
        if i in already_claimed:
            continue
        dist = levenshtein_distance(norm_callout, ref)
        if dist <= MAPPING_MAX_EDIT_DISTANCE and dist < best_dist:
            best_dist = dist
            best_idx  = i

    if best_idx is not None:
        return [best_idx], MAPPING_CONFIDENCE_FUZZY

    return [], 0.0


# ── Normalisation ──────────────────────────────────────────────────────────────

def _normalise_ref(ref_no: str) -> str:
    return ref_no.strip().lstrip("0") or "0"


def _normalise_callout(callout: dict) -> str:
    return callout["number"].strip().lstrip("0") or "0"
