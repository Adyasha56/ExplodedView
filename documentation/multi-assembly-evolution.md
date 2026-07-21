# Multi-Assembly PDF Support — Evolution & Fixes

## 1. Original Design (Single Assembly)

The pipeline was built assuming every uploaded PDF contains exactly **one assembly**: one diagram page and one BOM table page.

### How it worked

```
PDF upload
  → page_classifier: pick 1 diagram page + 1 BOM page
  → render diagram
  → preprocess → detect circles → read callouts → extract BOM → map → LLM
  → result.json (flat structure)
```

### Result schema (flat)

```json
{
  "diagramImagePath": "/static/outputs/<jobId>/diagram.png",
  "imageWidth": 2481,
  "imageHeight": 3508,
  "pageMap": { "diagramPageIndex": 0, "bomPageIndex": 1 },
  "hotspots": [...],
  "bom": [...],
  "mappings": [...],
  "unmappedHotspots": [...],
  "unpositionedBomRows": [...],
  "llmValidations": [...]
}
```

This worked correctly for clean 2-page PDFs.

---

## 2. The Problem — Multi-Assembly Combined PDF

When a user uploaded a 10-page combined PDF containing **5 assemblies** (each a [diagram, BOM] pair), the pipeline broke in two distinct ways.

### Problem A — Wrong assembly pair selected

The page classifier ranked BOM pages by table cell count and picked the single densest BOM. Its adjacent diagram was then chosen as "the" diagram.

For the test PDF:
- BOM pages by cell count: page 3 (100 cells), page 7 (100 cells), page 9 (55 cells), page 1 (50 cells), page 5 (20 cells)
- Classifier picked page 3 (highest cell count) → diagram = page 2

This happened to pick one correct pair, but:
- The other 4 assemblies were completely ignored
- On a different combined PDF, it could easily pick a BOM from one assembly and pair it with a diagram from a different assembly

### Problem B — ref 13 "NOT SHOWN" rows mixed into hotspot popups

The BOM for the Running Gear Axle assembly contains ref 13 with 7 rows — 1 visible part and 6 parts marked "NOT SHOWN":

```
13  35391127  CAP, DUST EZ                              ← visible, has a callout
13  23050180  HARNESS, TRAILER 2LT W/ 4 PIN CONNECT, NOT SHOWN
13  23168446  MOUNT, WINGED CABLE TIE PUSH, NOT SHOWN
13  35268788  TIE, CABLE .130 IN WD X 8.00 IN LG, NOT SHOWN
13  35222538  CLAMP, .56 IN RUBBER COATED SUPPORT ZN, NOT SHOWN
13  35279025  SCREW, M8-1.25 X 20 MM LG WASHER HEX HD, NOT SHOWN
13  96741962  SCREW, M8-1.25 X 25 LG FLANGE HEX HD TAP, NOT SHOWN
```

Because the mapping engine claimed all rows sharing ref 13, the hotspot 13 popup showed all 7 rows — including 6 parts that physically don't exist at any diagram location. This cluttered the UI and was semantically wrong.

---

## 3. Fixes Implemented

### Fix A — Page classifier returns all pairs

**File changed:** `ai-worker/modules/page_classifier.py`

**Before:** returned a single `dict` with one diagram+BOM pair.

**After:** returns a `list[dict]` of all discovered pairs, processing BOM candidates in **page order** (not cell-count order) so document sequence is preserved.

Algorithm:
1. Find all pages with ≥ 4 table cells (BOM candidates)
2. Iterate them in page order
3. For each BOM page, check if the previous page is a non-table page → pair them
4. Mark both pages as used so they can't be claimed by another pair
5. Fallback: check the next page if no previous page available
6. If no pairs found at all → fall back to (page 0, last page) with `confidence: low`

For the 10-page test PDF this discovers all 5 pairs correctly:
```
Assembly 0: diagram=page0, bom=page1   (Fuel System)
Assembly 1: diagram=page2, bom=page3   (Running Gear Axle)
Assembly 2: diagram=page4, bom=page5   (Wheel & Tire)
Assembly 3: diagram=page6, bom=page7   (Axle — colored duplicate)
Assembly 4: diagram=page8, bom=page9   (Sep Tank)
```

Single-assembly PDFs return a one-item list — no special case needed anywhere.

### Fix B — NOT SHOWN rows split out of mappings

**File changed:** `ai-worker/modules/mapping_engine.py`

**Before:** all BOM rows sharing a ref number (including NOT SHOWN ones) were placed in the hotspot's `bom[]` array.

**After:** after mapping, any row whose description contains `"NOT SHOWN"` is moved out of the hotspot's `bom[]` into a separate assembly-level `not_shown_bom_rows` list. Unclaimed NOT SHOWN rows also go there instead of `unpositionedBomRows`.

```python
def _is_not_shown(row: dict) -> bool:
    return "NOT SHOWN" in (row.get("description") or "").upper()
```

Result for ref 13:
- Hotspot 13 `bom[]` → `[{ "CAP, DUST EZ" }]` only
- Assembly `notShownBomRows` → the 6 NOT SHOWN rows

### Fix C — Pipeline loops over all pairs

**File changed:** `ai-worker/main.py`

**Before:** single linear pass through stages 1–9 for one assembly.

**After:** stages 2–8 run inside a loop over every pair returned by the classifier. Each assembly gets its own artifact subdirectory.

```
storage/outputs/<jobId>/
    assembly_0/diagram.png
    assembly_1/diagram.png
    assembly_2/diagram.png
    ...
    result.json   ← top-level, contains assemblies[]
```

### Fix D — Result schema restructured

**Files changed:** `ai-worker/modules/result_writer.py`, `backend/src/models/Result.model.js`, `backend/src/services/python.bridge.js`

**Before (flat):**
```json
{ "diagramImagePath": "...", "hotspots": [...], "bom": [...], ... }
```

**After (assemblies array):**
```json
{
  "processingDurationMs": 158666,
  "assemblies": [
    {
      "assemblyIndex": 0,
      "pageMap": { "diagramPageIndex": 0, "bomPageIndex": 1, "classificationConfidence": "high" },
      "diagramImagePath": "/static/outputs/<jobId>/assembly_0/diagram.png",
      "imageWidth": 2481,
      "imageHeight": 3508,
      "hotspots": [...],
      "bom": [...],
      "mappings": [...],
      "unmappedHotspots": [...],
      "unpositionedBomRows": [...],
      "notShownBomRows": [...],
      "llmValidations": [...]
    },
    { "assemblyIndex": 1, ... },
    ...
  ]
}
```

The Node.js bridge was updated to transform `diagramImagePath` inside each assembly (not a top-level field) to an Express static URL.

---

## 4. Validated Output (10-Page Combined PDF)

After all fixes, uploading the combined PDF produced 5 correctly processed assemblies:

| Assembly | Pages | Title | Mappings | NOT SHOWN rows |
|---|---|---|---|---|
| 0 | 0→1 | Fuel System Tank Installation | 6/9 BOM refs | 0 |
| 1 | 2→3 | Running Gear Standard Axle (B&W) | 10/13 BOM refs | 6 (ref 13) |
| 2 | 4→5 | Running Gear Wheel and Tire | 3/3 BOM refs ✓ | 0 |
| 3 | 6→7 | Running Gear Standard Axle (colour) | 8/13 BOM refs | 6 (ref 13) |
| 4 | 8→9 | Separation Sys Sep Tank Instl | 6/9 BOM refs | 1 (ref 7) |

LLM validations run independently per assembly and correctly scope their flags to each assembly's BOM.

---

## 5. Files Changed Summary

| File | Change |
|---|---|
| `ai-worker/modules/page_classifier.py` | Returns `list[dict]` of all pairs instead of one |
| `ai-worker/modules/mapping_engine.py` | Splits NOT SHOWN rows into `not_shown_bom_rows` |
| `ai-worker/modules/result_writer.py` | Writes `assemblies[]` schema |
| `ai-worker/main.py` | Loops over all pairs, collects assemblies |
| `ai-worker/config.py` | `get_artifact_paths(job_id, assembly_index)` uses subdirectories |
| `backend/src/models/Result.model.js` | Replaces flat schema with `AssemblySchema[]` |
| `backend/src/services/python.bridge.js` | Transforms `diagramImagePath` inside each assembly |
| `backend/src/controllers/results.controller.js` | Log line updated for assemblies structure |

**Files that did not change:** `callout_reader.py`, `circle_detector.py`, `image_preprocessor.py`, `bom_extractor.py`, `llm_resolver.py`, all route files. Each module still processes one diagram at a time — the loop in `main.py` is the only orchestration change.
