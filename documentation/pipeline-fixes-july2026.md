# Pipeline Fixes — July 2026

## Problem 1: Title Block & Footer False Positives

### What was happening
OCR and circle detection ran on the **full PDF page** (2481×3508px), which includes:
- A plain-text title block at the top (~top 20%) containing serial codes like `D47`, `LSWKUB-60HZ-T4F` etc.
- A footer at the bottom (~bottom 10%) containing page numbers like `Page ① of 2`

This caused numbers from those text regions (e.g. `4` from `Serial Code D47`, `60` from `LSWKUB-60HZ`) to be detected as callout hotspots and mapped to wrong BOM parts.

### Root cause
The pipeline rendered the full page as an image and passed it to PaddleOCR without cropping out the non-diagram regions.

### Fix: Drawing area crop (`main.py` — `_detect_drawing_crop`)

Added a crop step (Stage 2b) between PDF rendering and image preprocessing. Three approaches were tried:

| Attempt | Approach | Outcome |
|---|---|---|
| 1 | PyMuPDF `get_drawings()` looking for a large rectangle | Failed — drawing frame is 4 separate line segments, not a single rect |
| 2 | OpenCV morphological MORPH_OPEN to find long horizontal rows | Failed — 1px border lines with rendering gaps broke the open operation |
| 3 | HoughLinesP to find long horizontal line segments | Failed silently — `cv2` was imported inside `run()` (local scope) but `_detect_drawing_crop` is a module-level function and couldn't see it |

**Fix that worked**: Switched to a **horizontal projection profile** approach:
1. Otsu binarize the image (dark pixels = 0)
2. For each row, count dark pixels AND find the longest contiguous dark run
3. Rows where dark pixels ≥ 30% of width AND longest run ≥ 25% of width are "border rows"
4. Top border = topmost qualifying row below 5% of image height
5. Bottom border = bottommost qualifying row above 95% of image height
6. Crop to `[border_top - 2 : border_bottom + 2]`

Also fixed the `NameError`: added `import cv2` inside `_detect_drawing_crop` since it's a module-level function outside the scope where `cv2` was previously imported.

**Result**: Assembly diagrams now crop from 3508px → ~2504px, removing the title block (581px) and footer (423px).

---

## Problem 2: UnicodeEncodeError on Windows

### What was happening
`strategy_e_recovery.py` line 288 used `→` (U+2192) and `—` (U+2014) in a `logger.info` format string. Windows cp1252 console encoding cannot encode these characters, crashing the pipeline log output.

### Fix (`strategy_e_recovery.py`)
Replaced non-ASCII characters with ASCII equivalents:
```python
# Before
"Strategy E: ref=%s → %s (x=%d, y=%d, r=%d) conf=%.2f — %s"
# After
"Strategy E: ref=%s -> %s (x=%d, y=%d, r=%d) conf=%.2f - %s"
```

---

## Problem 3: Valid Callouts Filtered After Crop

### What was happening
After the crop started working, assemblies that previously had callouts near the top of the drawing area (e.g., Assembly 4 refs 3, 4, 5) started showing as "No position". The crop was correct visually but refs were being filtered.

### Root cause
All callout strategies (A, B, C) and Strategy E applied a **10% border zone** filter — originally designed to exclude the title block. But after cropping, the cropped image starts at the drawing frame border, so the 10% zone was now cutting into the actual drawing area where valid callouts live.

### Fix (`callout_reader.py`, `strategy_e_recovery.py`)
Reduced all border zone percentages from 10%/90% → **3%/97%**:

| Location | Before | After |
|---|---|---|
| Strategy A (PyMuPDF), `callout_reader.py` | `0.10` / `0.90` | `0.03` / `0.97` |
| Strategy B (PaddleOCR tiles), `callout_reader.py` | `0.10` / `0.90` | `0.03` / `0.97` |
| Strategy C (per-circle OCR), `callout_reader.py` | `0.10` / `0.90` | `0.03` / `0.97` |
| Strategy E (Gemini unresolved circle filter) | `0.10` / `0.90` | `0.03` / `0.97` |

The crop now handles title block exclusion; 3% is sufficient to avoid artifacts from the drawing frame border itself.

---

## Problem 4: "New PDF" Button Not Working

### What was happening
Clicking "New PDF" called `handleReset()` which set `jobId = null`. But `useJobPoller` maintained its `job`, `result`, and `error` state internally — resetting `jobId` stopped polling but did not clear the old result. So `if (result)` remained true and the viewer kept showing instead of returning to the drop zone.

### Fix (`frontend/src/hooks/useJobPoller.js`)
Added state reset at the start of the `useEffect` that runs when `jobId` changes:
```js
useEffect(() => {
  setJob(null);
  setResult(null);
  setError(null);
  if (!jobId) return;
  // ... rest of polling logic
}, [jobId]);
```

---

## Problem 5: Yellow/Colored Callout Circles Not Detected

### What was happening
Assembly 3 (UI "Assembly 4", Running Gear Standard Axle) has callout circles with **yellow/amber fill** for all 13 refs. The circle detector found only **1 circle**, causing refs 3–9 to remain unpositioned.

### Root cause
The image preprocessor uses `THRESH_BINARY_INV + THRESH_OTSU`. Yellow is a bright color (grayscale ≈ 220+), so after binary inversion:
- Bright yellow fill → **black/invisible** in binary image
- Only the dark outline text (the ref number inside) remains white
- A single digit "3" or "8" is not circular → rejected by circularity filter

White-outlined callouts have a dark ring that survives inversion correctly. Yellow-filled ones don't.

### Failed approach (do not re-attempt)

An earlier attempt added a yellow HSV mask inside the preprocessor, forcing matched pixels to dark `(30, 30, 30)` before binarization. This made yellow circles visible as solid white disks — but also caught **large non-circular colored elements** on the diagram (coloured axle bodies, coupling brackets) when the saturation floor was lowered to S≥15 to catch pale cream circles. Those elements became large irregular white blobs that:
1. Generated contours with huge `minEnclosingCircle` radii
2. Dominated the deduplication sort (sorted largest-first)
3. Even with the dedup condition changed to `distance < min(r1, r2)`, 59 passing candidates still collapsed to 1 — because the large blob sat near the diagram centre and its own accepted entry had a wide exclusion zone

Raising S back to 60 fixed the blob problem but missed pale cream circles (S ≈ 25–35). There was no saturation value that caught cream circles without also catching large non-circular parts.

### Fix: Separate parallel detection pass (`circle_detector.py` + `main.py`)

The preprocessor's binary pipeline is **not modified**. Instead a second detection pass runs on the original color image using `cv2.connectedComponentsWithStats` on an HSV mask:

```python
# circle_detector.py — detect_colored_circles()
mask = cv2.inRange(hsv, (12, 20, 140), (45, 255, 255))
# H=12-45: amber to yellow; S≥20 catches cream (S≈25-35); V≥140 filters shadows
```

Each connected component is tested with **shape filters** rather than perimeter-based circularity:

| Filter | Threshold | Rejects |
|---|---|---|
| Equivalent radius (`sqrt(area/π)`) | 12–120 px | noise, whole-diagram blobs |
| Aspect ratio (`min(w,h)/max(w,h)`) | ≥ 0.70 | elongated axle beams, straps |
| Compactness (`area / (w·h)`) | 0.50–0.95 | sparse/filled rectangles |

Why shape filters beat perimeter-based circularity here:
- `cv2.arcLength` overestimates perimeter on pixelated small circles → false low-circularity scores
- An elongated axle beam fails aspect ratio immediately regardless of saturation overlap
- A perfect filled-circle disk: aspect ≈ 1.0, compactness ≈ π/4 ≈ 0.785 → always passes

`main.py` Stage 4 now runs both passes and merges:

```python
circles        = detect_circles(preprocessed)          # binary pass (dark-outlined)
colored_circles = detect_colored_circles(diagram_image) # color pass (filled)
circles        = merge_circle_lists(circles, colored_circles)  # dedup combined
```

The preprocessor's yellow mask was tightened back to S≥60 (only vivid yellow, not cream) so it no longer catches large colored diagram parts.

**Result**: All 13 callout circles detected for the Running Gear assembly. Other assemblies (white-outlined circles, no colored fills) unaffected — `detect_colored_circles` returns 0 components when no yellow/amber pixels exist.

---

## Problem 6: Strategy E Gemini Timeout

### What was happening
Strategy E (Gemini Vision recovery) was timing out after 30 seconds on some assemblies, especially when sending large images with many missing refs.

### Fix (`modules/strategy_e_recovery.py`)
Increased minimum timeout from 30s to 60s:
```python
# Before
response = requests.post(url, json=payload, timeout=max(LLM_TIMEOUT_SECONDS, 30))
# After
response = requests.post(url, json=payload, timeout=max(LLM_TIMEOUT_SECONDS, 60))
```

---

## Problem 7: LLM Resolver JSON Parse Failure ("Extra data")

### What was happening
The pipeline crashed with `json.decoder.JSONDecodeError: Extra data` in `llm_resolver.py`. Gemini occasionally appended trailing text or a newline after the closing `}` of the JSON response.

### Fix (`ai-worker/modules/llm_resolver.py`)
Replaced `json.loads(raw_text)` with `json.JSONDecoder().raw_decode(raw_text)`, which consumes only the first valid JSON object and silently ignores any trailing content.

---

## Problem 8: Gemini 503 Errors Not Retried

### What was happening
Strategy E failed permanently on transient Gemini server errors (HTTP 503), even though the retry logic in `gemini_http.py` was intended to handle transient failures.

### Root cause
The retry condition only checked for `429` (rate limit). A `503` (service unavailable) triggered `raise_for_status()` immediately with no backoff.

### Fix (`ai-worker/utils/gemini_http.py`)
Changed the condition from `response.status_code != 429` to `response.status_code not in (429, 503)`. Both codes now retry with exponential backoff (5s, 15s) up to 2 times before failing.

---

## Problem 9: Hotspot Positions Change Across Uploads (LLM Non-Determinism)

### What was happening
Uploading the same PDF twice produced different hotspot positions for colored callout circles. Strategy E assigned different circle candidates to BOM refs on each run.

### Root cause
Both Gemini API calls (Strategy E and llm_resolver) were sent without `temperature: 0`. The model sampled different outputs each call, so circle-to-ref assignments varied between runs.

### Fix (`ai-worker/modules/strategy_e_recovery.py`, `ai-worker/modules/llm_resolver.py`)
Added `"temperature": 0` to `generationConfig` in both API payloads. Gemini now returns identical results for identical inputs.

---

## Problem 10: OCR Misclassifies Digits Inside Colored Circles ("2" Read as "7")

### What was happening
For assemblies with yellow/amber callout circles, PaddleOCR misread the digit inside — e.g., ref "2" was read as "7". This placed a hotspot at the wrong BOM mapping position.

### Root cause
Yellow fill reduces OCR contrast and introduces color channel noise that confuses digit classification. The OCR result was used directly with the wrong digit, which then matched the wrong BOM row.

### Attempted (rejected) fix
Snapping the OCR callout position to the detected colored circle center — this moved the coordinate but kept the wrong digit, still producing a wrong mapping.

### Final fix (`ai-worker/main.py`)
After `read_callouts()` returns, any OCR callout whose `(x, y)` falls within the radius of a detected colored circle is dropped. Strategy E (Gemini Vision) handles colored circles correctly and returns both the right digit and the right coordinates.

**Behavior with this fix:**
- LLM enabled: colored circle refs read by Gemini Vision → correct digit + correct position
- LLM disabled: colored circle refs remain unpositioned → no wrong data shown to user

---

## Summary of Files Changed (Problems 1–10)

| File | Change |
|---|---|
| `ai-worker/main.py` | Added Stage 2b crop; switched to projection-profile approach; added `import cv2` in `_detect_drawing_crop`; Stage 4 now runs binary + color circle detection passes and merges results |
| `ai-worker/modules/image_preprocessor.py` | Yellow mask tightened back to S≥60 (vivid only); cream circles now handled by separate pass |
| `ai-worker/modules/circle_detector.py` | Added `detect_colored_circles()` (HSV connected-component + shape filters) and `merge_circle_lists()` |
| `ai-worker/modules/callout_reader.py` | Reduced border zone from 10% to 3% in Strategies A, B, C |
| `ai-worker/modules/strategy_e_recovery.py` | Fixed `→`/`—` Unicode chars; reduced border zone to 3%; increased timeout to 60s |
| `ai-worker/.env` | `LLM_ENABLED` toggled during testing (currently `true`) |
| `backend/src/models/Result.model.js` | Added `paddleocr_enhanced` and `gemini_vision` to `extractionMethod` enum |
| `frontend/src/hooks/useJobPoller.js` | Reset `job`/`result`/`error` state when `jobId` becomes null (New PDF button fix) |

---

---

# Cloud Run Deployment Fixes — 2026-07-20 to 2026-07-21

These bugs were discovered after deploying to Google Cloud Run (asia-southeast1). The pipeline worked correctly on local Windows but failed in the Cloud Run Linux Docker container.

---

## Problem 11: Python Diagnostic Logs Invisible in Cloud Run

### What was happening
All Python `logger.info` / `logger.warning` output was invisible in Cloud Run logs. The pipeline appeared to run silently — no OCR diagnostics, no Strategy E logs, nothing useful for debugging.

### Root cause
`utils/logger.py` used `logging.StreamHandler(sys.stdout)`. Node.js reads the Python subprocess's **stdout** as the newline-delimited JSON protocol channel (`{"status": "processing", ...}`). Non-JSON lines from Python were not valid protocol messages, so `python.bridge.js` caught them in a `logger.debug()` call — which is filtered out in Cloud Run's default log level (INFO and above).

### Fix (`ai-worker/utils/logger.py`)
Changed the handler stream from `sys.stdout` to `sys.stderr`:
```python
# Before
_handler = logging.StreamHandler(sys.stdout)
# After
_handler = logging.StreamHandler(sys.stderr)
```
Node.js `python.bridge.js` forwards all Python stderr lines as `logger.warn(...)`, which appears in Cloud Run logs as `[warn]` entries — always visible regardless of log level.

**Result**: All Python pipeline logs now visible in Cloud Run as `[warn]` prefixed entries.

---

## Problem 12: Strategy E (Gemini Vision) Timing Out on Colored PDFs in Cloud Run

### What was happening
Strategy E timed out when processing colored PDFs on Cloud Run. The non-colored PDF took ~54s (borderline success); the colored PDF triggered a 503 on the first attempt, then a read timeout after 60s on the retry.

**Log evidence:**
```
Strategy E: Gemini call FAILED after 60s+ (ReadTimeout)
```

### Root cause
The colored diagram was 2481×2504px. Encoding it as a full-resolution PNG produced a ~5–8MB payload. Sending this from Cloud Run's Singapore region (`asia-southeast1`) to Gemini's US endpoints over the public internet was too slow — the response body arrived after the 60s timeout.

Local testing was unaffected because local → Gemini latency is lower and there is no container cold-start overhead.

### Fix (`ai-worker/modules/strategy_e_recovery.py`)
Added image resize in `_encode_image()` before PNG encoding — max 1500px on the longest side:
```python
def _encode_image(image: np.ndarray) -> str:
    h, w = image.shape[:2]
    max_dim = 1500
    if max(h, w) > max_dim:
        scale = max_dim / max(h, w)
        new_w = int(w * scale)
        new_h = int(h * scale)
        image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
        logger.info("_encode_image: resized %dx%d -> %dx%d for Gemini payload", w, h, new_w, new_h)
    success, buf = cv2.imencode(".png", image)
    ...
```
Also increased the minimum timeout from `max(LLM_TIMEOUT_SECONDS, 60)` to `max(LLM_TIMEOUT_SECONDS, 120)`.

**Result**: Non-colored PDF: ~11s (was 54s). Colored PDF: ~10s (was >60s timeout). Callout circle numbers remain legible at 1500px — Gemini confirmed 1.00 confidence on all detections.

---

## Problem 13: PaddleOCR Non-Deterministic Results on Cloud Run

### What was happening
PaddleOCR returned different callout sets across Cloud Run deployments of the same PDF:
- Revision 00007: OCR returned 0 callouts (all tiles returned None or empty)
- Revision 00008 and later: OCR returned 6–12 callouts per run, but the specific refs varied

Same PDF, same Docker image tag — different OCR results.

### Diagnostic logging added (`ai-worker/modules/callout_reader.py`)
Added `[OCR-DIAG]` logs per tile showing shape, memory before/after, raw box count, and first 8 text+score samples:
```
[OCR-DIAG] tile 2/3 rows=626-1668 shape=2481x1042 mem_before=1298MB
[OCR-DIAG] tile 2: 5 raw box(es) mem_after=1356MB sample=[('1', 0.906), ('7', 0.595), ...]
[OCR-DIAG] tile 2: 2/5 box(es) passed digit+score+zone filter
```

### Root cause
Best current hypothesis: non-deterministic transitive dependency resolution in Docker builds. PaddleOCR's inference is sensitive to the exact versions of `numpy`, `opencv-python`, and `paddlepaddle` resolved at build time. Different builds may get slightly different minor versions, producing different OCR outputs.

Memory was ruled out: peak usage reaches ~2100MB but the pipeline completes. Model files were confirmed present (inference runs, just returns variable results).

### Status
Not fully resolved. Strategy E (Gemini Vision) currently compensates for missed OCR detections on colored circle refs. Strategy D (per-circle PaddleOCR with multi-variant voting) recovers a subset. Pinning exact dependency versions in `requirements.txt` is the recommended next step.

---

## Problem 14: Strategy E JSON Parse Failure (Gemini Returns Malformed JSON)

### What was happening
Strategy E failed with:
```
Strategy E: Gemini call FAILED after 9876 ms
(Expecting ',' delimiter: line 57 column 4 (char 1812))
```
All 9 missing refs remained unpositioned despite Gemini responding in under 10s.

### Root cause
Gemini `gemini-3.5-flash` occasionally produces JSON responses with:
1. **Markdown fences** — wraps the JSON in ` ```json ... ``` `
2. **Trailing content** — appends prose or a newline after the closing `}`
3. **Internal malformation** — a missing comma or extra character deep inside the JSON object (char 1812 in this case)

`json.loads()` throws on all three of these. The exception was caught by the outer `except Exception` block and the entire Strategy E result was discarded.

### Fix (`ai-worker/modules/strategy_e_recovery.py`)
Three-layer hardening of the JSON parse in `_call_gemini()`:

1. **Strip markdown fences** before parsing:
```python
cleaned = raw_text
if cleaned.startswith("```"):
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()
```

2. **Use `raw_decode` instead of `json.loads`** — consumes only the first valid JSON object, ignores trailing content:
```python
parsed, _ = json.JSONDecoder().raw_decode(cleaned)
```

3. **Diagnostic window on failure** — logs ±300 chars around the error position so the exact malformation is visible in logs without exposing API keys:
```python
except json.JSONDecodeError as e:
    pos = e.pos
    win_s = max(0, pos - 300)
    win_e = min(len(cleaned), pos + 300)
    logger.warning(
        "Strategy E: JSON parse failed at pos=%d (response_len=%d): %s — "
        "context [%d:%d]: %r",
        pos, len(cleaned), e.msg, win_s, win_e, cleaned[win_s:win_e],
    )
    raise
```

**Note**: The `raw_decode` fix handles trailing-content and fence cases. If the error is at char 1812 inside a 2000-char response, it is internally malformed JSON — the diagnostic window will identify what Gemini wrote at that position on the next occurrence.

---

## Problem 15: OCR False Positive "28" Triggering Unnecessary Gemini Call

### What was happening
PaddleOCR consistently misread a diagram element (part of the "Bobcat" watermark or footer text) as `"28"` with 0.938 confidence. This hotspot had no BOM match (the BOM for this assembly has refs 1–13 only). Despite no possible mapping, `llm_resolver` was called with `"28"` as an unmapped hotspot — making a full Gemini API call that always failed or got rate-limited (429):

```
llm_resolver: calling Gemini — 0 fuzzy mapping(s), 1 unmapped hotspot(s)
Gemini 429 (attempt 1) — retrying in 5s
Gemini 429 (attempt 2) — retrying in 15s
llm_resolver: LLM call failed after 20528 ms (429 ...)
```

### Root cause
`llm_resolver` was called whenever `unmapped_hotspots` was non-empty, without checking whether any of those hotspot refs could conceivably map to a BOM row.

### Fix (`ai-worker/main.py`)
Before calling `llm_resolver`, filter `unmapped_hotspots` to only those whose normalized ref number exists in the BOM ref set. Refs not in the BOM are kept in the final result but not sent to Gemini:

```python
_norm_r = lambda r: str(r).strip().lstrip("0") or "0"
_bom_ref_set = {_norm_r(r["ref_no"]) for r in bom_rows}
_all_unmapped     = mapping_result["unmapped_hotspots"]
_valid_unmapped   = [h for h in _all_unmapped if _norm_r(h["number"]) in _bom_ref_set]
_invalid_unmapped = [h for h in _all_unmapped if _norm_r(h["number"]) not in _bom_ref_set]
# Only call llm_resolver if there's something valid to resolve
if _valid_unmapped or _has_fuzzy:
    ...call llm_resolver with _valid_unmapped only...
    # Restore invalid refs to final result (visible but not sent to Gemini)
    mapping_result["unmapped_hotspots"] += _invalid_unmapped
```

**Result**: `"28"` is filtered before llm_resolver, logged as excluded, and preserved in the final unmapped list. The unnecessary Gemini call is skipped entirely, saving ~20s and one quota unit.

---

## Problem 16: Colored OCR Fallback Creating Duplicate Hotspots

### What was happening
After introducing the colored OCR fallback mechanism (save dropped colored-circle OCR callouts; restore if Strategy E doesn't resolve them), refs 1, 3, and 10 appeared as **unmapped hotspots** in the result even though they were successfully detected and mapped:

```
unmapped hotspots: ['28', '1', '10', '3']
unpositioned BOM rows: ['4', '5', '6', '8', '9']
```
Refs 1, 3, 10 appeared in the BOM list as correctly mapped in the frontend (because `llm_resolver` compensated), but the raw pipeline output was incorrect.

### Root cause
The fallback restoration check only excluded refs recovered by Strategy E (`_strategy_e_recovered_refs`). It did **not** check refs already resolved by Strategy D.

Timeline:
1. OCR detects refs 1, 3, 7, 10 inside colored circles → saved as fallbacks, dropped from `callouts`
2. Strategy D recovers refs 1, 3, 2, 10 at correct colored circle centers → added to `callouts`
3. Strategy E gets 429 → `_strategy_e_recovered_refs = {}`
4. Fallback restoration: refs 1, 3, 10 pass the check (`not in _strategy_e_recovered_refs`) → **added again**
5. `callouts` now has two entries each for refs 1, 3, and 10
6. Mapping engine maps the Strategy D version → BOM row taken
7. The duplicate OCR version has nowhere to map → becomes "unmapped hotspot"

### Fix (`ai-worker/main.py`)
Changed the deduplication check from `_strategy_e_recovered_refs` (Strategy E only) to `_already_resolved` (all currently resolved refs in `callouts`):

```python
# Before
_restored = [
    fb for ref, fb in colored_ocr_fallbacks.items()
    if ref not in _strategy_e_recovered_refs and ref in _bom_refs
]

# After
_already_resolved = {_norm(c["number"]) for c in callouts}
_restored = [
    fb for ref, fb in colored_ocr_fallbacks.items()
    if ref not in _already_resolved and ref in _bom_refs
]
```

At the time of restoration, `callouts` already contains all Strategy D and Strategy E results. So `_already_resolved` correctly covers all upstream sources.

**Result**: Refs 1, 3, 10 resolved by Strategy D are skipped at restoration. No duplicate hotspots. Only genuinely unresolved BOM refs that passed OCR are restored from the fallback.

---

## Summary of Files Changed (Problems 11–16)

| File | Change |
|---|---|
| `ai-worker/utils/logger.py` | Changed `StreamHandler` from `sys.stdout` → `sys.stderr` so Python logs appear in Cloud Run |
| `ai-worker/modules/strategy_e_recovery.py` | Resize image to max 1500px before Gemini encoding; increase timeout to 120s; strip markdown fences + use `raw_decode` + log diagnostic window on JSON parse failure; added `import re` |
| `ai-worker/modules/callout_reader.py` | Added `[OCR-ENV]` and `[OCR-DIAG]` diagnostic logging per tile and per Strategy C circle |
| `ai-worker/main.py` | Save colored OCR callouts as fallbacks instead of discarding; restore only unresolved BOM refs checking all `callouts` (not just Strategy E); filter non-BOM unmapped refs before `llm_resolver`; added `[CIRCLE]`/`[CALLOUT]`/`[STRATEGY_D]`/`[STRATEGY_E]`/`[HOTSPOTS]` pipeline counters |
