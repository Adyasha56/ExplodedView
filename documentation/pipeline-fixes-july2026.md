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

## Summary of Files Changed

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
