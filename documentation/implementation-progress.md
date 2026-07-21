# ExplodedView — Implementation Progress

> Last updated: 2026-07-15
> Status: Milestone 2A complete · Milestone 2B complete · Milestone 2C complete · Milestone 2D in progress (architecture + pre-LLM changes done, end-to-end test pending)

---

## What This System Does

Takes a mechanical engineering PDF (exploded-view diagram + BOM table) and produces structured JSON that maps every numbered callout on the diagram to its corresponding BOM row. The frontend then renders an interactive overlay showing part names, quantities, and part numbers on top of the diagram image.

---

## Project Structure

```
ExplodedView/
├── .gitignore                   ← protects .env, venv, node_modules, storage/
├── documentation/
│   ├── system-design.md         ← full architecture doc (v2)
│   ├── backend-guide.md         ← backend data-flow + testing guide
│   └── implementation-progress.md  ← this file
├── backend/                     ← Node.js / Express API
├── ai-worker/                   ← Python pipeline
└── storage/
    ├── uploads/                 ← incoming PDFs (auto-deleted after processing)
    └── outputs/                 ← per-job artifacts + final result.json
```

---

## Milestone 1 — Scaffolding ✅ COMPLETE

Everything needed to run the project from a fresh clone.

| File | Purpose |
|---|---|
| `.gitignore` | Ignores `.env`, `node_modules/`, `venv/`, `__pycache__/`, `storage/uploads/*`, `storage/outputs/*` |
| `storage/uploads/.gitkeep` | Keeps uploads dir in git without committing uploaded files |
| `storage/outputs/.gitkeep` | Same for outputs dir |
| `backend/package.json` | Node deps: express, cors, dotenv, mongoose, multer@2, uuid@11, winston |
| `backend/jsconfig.json` | Sets `"module": "commonjs"` — suppresses VS Code ESM hints project-wide |
| `ai-worker/requirements.txt` | Python deps (see table below) |

### Python Dependencies (`ai-worker/requirements.txt`)

| Package | Version | Role |
|---|---|---|
| PyMuPDF | 1.24.5 | PDF text + image extraction (Strategy A — primary) |
| pdfplumber | 0.11.1 | BOM table extraction from vector PDFs |
| opencv-python-headless | 4.6.0.66 | Contour detection, CLAHE, morphological ops. Headless = no GUI dep. Pinned for paddleocr compat. |
| numpy | 1.26.4 | Array ops required by OpenCV |
| paddlepaddle | 2.6.2 | PaddleOCR runtime engine (CPU build) |
| paddleocr | 2.7.3 | OCR inference — fallback when direct extraction fails |
| Pillow | 10.3.0 | Image I/O for PaddleOCR and preprocessing |
| python-Levenshtein | 0.25.1 | Edit-distance fuzzy matching (hotspot → BOM) |
| python-dotenv | 1.0.1 | Loads `.env` into `os.environ` |
| setuptools | latest | Required by paddlepaddle at import time — was missing, caused ImportError |

> **Python version requirement:** 3.12. PyMuPDF 1.24.5 has no pre-built wheel for 3.13 and would require Visual Studio Build Tools to compile from source. Use `py -3.12 -m venv venv`.

---

## Milestone 2A — Backend ✅ COMPLETE (all 4 endpoint tests passed)

### `backend/.env`

```
PORT=5000
NODE_ENV=development
MONGO_URI=mongodb+srv://...@cluster0.knxor.mongodb.net/ExplodedView
STORAGE_PATH=../storage
PYTHON_EXECUTABLE=D:\ExplodedView\ai-worker\venv\Scripts\python.exe
PYTHON_WORKER_PATH=../ai-worker/main.py
JOB_TTL_DAYS=7
MAX_UPLOAD_SIZE_MB=50
```

> **Why the full venv path:** `PYTHON_EXECUTABLE=python` invokes system Python, which has none of the pipeline dependencies. The venv Python must be specified with its absolute path. `config.js` detects whether the value contains a path separator and resolves it relative to `backend/` accordingly.

### Config — `backend/src/config.js`

Central config. Resolves `storage.root` as `path.resolve(__dirname, '..', STORAGE_PATH)` — relative to `backend/src/`, going up to the project root then into `storage/`. All other modules import from here; nothing hardcodes a path or threshold.

### Logger — `backend/src/utils/logger.js`

Winston logger. Console output only (no log files). Format: `HH:mm:ss [level] message`. Colorized by level.

### PipelineState — `backend/src/constants/pipeline.js`

Shared enum used by both Node.js and Python to track which stage the pipeline is in. Prevents string drift between the two processes.

```
UPLOADING → PAGE_CLASSIFICATION → PDF_RENDERING → IMAGE_PREPROCESSING
→ CIRCLE_DETECTION → CALLOUT_READING → BOM_EXTRACTION → MAPPING
→ LLM_VALIDATION → RESULT_GENERATION → COMPLETED / FAILED
```

### Job Model — `backend/src/models/Job.model.js`

MongoDB document tracking a single processing job.

| Field | Type | Notes |
|---|---|---|
| `jobId` | String | UUID v4, unique, indexed |
| `filename` | String | Original uploaded filename |
| `fileSizeBytes` | Number | For display + analytics |
| `status` | Enum | `pending` / `processing` / `done` / `error` |
| `pipelineStep` | Enum | One of the PipelineState constants above |
| `errorMessage` | String | Populated on failure |
| `createdAt` | Date | Auto (timestamps: true) |
| `updatedAt` | Date | Auto (timestamps: true) |

TTL index on `createdAt` → MongoDB auto-deletes jobs after `JOB_TTL_DAYS` days (default 7).

### Result Model — `backend/src/models/Result.model.js`

Stores the final pipeline output for a job.

| Field | Notes |
|---|---|
| `jobId` | Links to Job |
| `diagramImagePath` | Express URL to `diagram.png`: `/static/outputs/<jobId>/diagram.png` |
| `imageWidth / imageHeight` | Pixel dimensions of the diagram image |
| `processingDurationMs` | Total pipeline time |
| `pageMap` | Which PDF page was diagram vs BOM |
| `hotspots[]` | Each detected callout: `{ number, x, y, radius, extractionMethod }` |
| `bom[]` | Each BOM row: `{ refNo, partNo, description, qty }` |
| `mappings[]` | One entry per hotspot: `{ hotspotNumber, x, y, radius, confidence, bom: [BomRowSchema] }` |
| `unmappedHotspots[]` | Hotspots detected on diagram with no matching BOM row |
| `unpositionedBomRows[]` | BOM rows whose callout was never detected by OCR (NOT fabricated with coordinates) |
| `llmValidations[]` | LLM-produced validation items (fuzzy_validation / hotspot_suggestion / consistency_flag) |

### Upload Middleware — `backend/src/middleware/upload.middleware.js`

multer v2 `diskStorage`. Generates a UUID v4, attaches it to `req.jobId`, saves file as `storage/uploads/<jobId>.pdf`. `fileFilter` rejects anything that isn't `application/pdf` (returns 415). Size limit enforced via `MAX_UPLOAD_SIZE_MB` (returns 413 via global error handler).

### Controllers

| File | Route | What it does |
|---|---|---|
| `upload.controller.js` | `POST /api/upload` | Validates `req.file`, creates Job (status: pending), fire-and-forgets Python bridge, returns `202 { jobId, status, message }` |
| `jobs.controller.js` | `GET /api/jobs/:jobId` | Returns `{ jobId, filename, status, pipelineStep, errorMessage, createdAt, updatedAt }` |
| `results.controller.js` | `GET /api/results/:jobId` | Returns Result doc. `409` if not done yet, `422` if job errored, `500` if Result doc is missing |

### Python Bridge — `backend/src/services/python.bridge.js`

Spawns `python main.py --job-id <id> --storage-path <path>` as a child process. Uses Node's `readline` on stdout to parse one JSON line at a time.

- Each `{ step, status: "start" }` line → updates Job's `pipelineStep` in MongoDB
- `{ status: "done" }` → reads `result.json`, saves Result doc, marks Job `done`, calls cleanup
- `{ status: "error", message }` → marks Job `error`
- Process crash → marks Job `error`

### Cleanup Service — `backend/src/services/cleanup.service.js`

- `cleanupJobFiles(jobId)` — deletes `uploads/<jobId>.pdf` and `preprocessed.png`. Keeps `diagram.png` and `result.json` (needed by frontend).
- `purgeJobOutputDir(jobId)` — removes entire `outputs/<jobId>/` when a job is fully expired.

### App Entry Point — `backend/src/app.js`

Mounts:
- `POST /api/upload` — multer middleware → upload controller
- `GET /api/jobs/:jobId` — jobs controller
- `GET /api/results/:jobId` — results controller
- `GET /static/outputs` — `express.static` serving diagram images
- `GET /health` — returns `{ status: "ok", timestamp }`

Global error handler catches multer errors and maps them to 413/415 before Express's default 500.

---

## Milestone 2B — Python Pipeline ✅ COMPLETE (7/7 modules, end-to-end test passed)

### AI Worker Config — `ai-worker/config.py`

All tunable constants for the Python pipeline. Nothing in any module is hardcoded.

Key values:
- `STORAGE_ROOT` — resolved from `STORAGE_PATH` env var relative to `ai-worker/`
- `get_artifact_paths(job_id)` — returns dict of all per-job file paths (`diagram.png`, `preprocessed.png`, `result.json`, etc.)
- `PDF_RENDER_DPI = 300`
- `PAGE_CLASSIFIER_MIN_TABLE_CELLS = 4`
- `CIRCLE_CIRCULARITY_THRESHOLD = 0.75`
- `CIRCLE_MIN_RADIUS_PX = 12`, `CIRCLE_MAX_RADIUS_PX = 80`
- `MAPPING_MAX_EDIT_DISTANCE = 1`
- `MAPPING_CONFIDENCE_EXACT = 1.0`, `MAPPING_CONFIDENCE_FUZZY = 0.7`
- `LLM_ENABLED = False` (Gemini disabled until Milestone 2D)
- `DEBUG = False` (set `DEBUG=true` in `.env` to write intermediate artifact images)

### PipelineState (Python) — `ai-worker/constants/pipeline_state.py`

Mirrors `backend/src/constants/pipeline.js` exactly. `PipelineState(str, Enum)` so values can be emitted as plain strings over stdout without serialization. `STEP_LABELS` dict maps each state to the lowercase string the bridge expects.

### Logger — `ai-worker/utils/logger.py`

`get_logger(name)` returns a child logger under `pipeline.<name>`. All modules use this — never `print()`.

### Interfaces (Protocols) — `ai-worker/interfaces/`

Three `typing.Protocol` classes defining swappable component contracts:

| Interface | Method | Returns |
|---|---|---|
| `OcrEngine` | `extract_text(image: np.ndarray)` | `list[{ "text": str, "score": float }]` |
| `PdfTextExtractor` | `extract_text_in_rect(page, x, y, w, h)` | `str \| None` |
| `MappingStrategy` | `match(hotspot_number, bom_ref_numbers)` | `(matched_ref \| None, confidence)` |

These let you swap OCR engines or matching strategies without touching caller code.

### Orchestrator — `ai-worker/main.py`

CLI entry point. Args: `--job-id`, `--storage-path`. Calls `emit_step(step)` before each stage (prints JSON to stdout so the Node bridge can update the DB). Stages wired in order:

1. `page_classifier.classify_pages()`
2. PDF rendering (inline fitz — renders diagram page to PNG)
3. `image_preprocessor.preprocess()`
4. `circle_detector.detect_circles()`
5. `callout_reader.read_callouts()`
6. `bom_extractor.extract_bom()`
7. `mapping_engine.map_hotspots_to_bom()`
8. `llm_resolver.resolve_with_llm()` — skipped unless `LLM_ENABLED=true` and unresolved items exist
9. `result_writer.write_result()`

---

### Module Status

| Module | File | Status | Test Result |
|---|---|---|---|
| Page Classifier | `modules/page_classifier.py` | ✅ Complete | diagram=0, bom=1, confidence=high |
| Image Preprocessor | `modules/image_preprocessor.py` | ✅ Complete | 170,761 non-zero px, ~130ms |
| Circle Detector | `modules/circle_detector.py` | ✅ Complete | 20 circles (mechanical features) |
| Callout Reader | `modules/callout_reader.py` | ✅ Complete | 12/17 callouts found |
| BOM Extractor | `modules/bom_extractor.py` | ✅ Complete | 18 rows, all qty populated |
| Mapping Engine | `modules/mapping_engine.py` | ✅ Complete | 12 mapped, 5 unpositioned BOM rows |
| Result Writer | `modules/result_writer.py` | ✅ Complete | result.json written with nested bom[] |
| LLM Resolver | `modules/llm_resolver.py` | ✅ Complete | Gemini REST API, graceful fallback |

**End-to-end pipeline test:** Passed. All 9 stages complete. Total time ~45 seconds (PaddleOCR cold start dominates).

---

### `page_classifier.py` — How It Works

**Input:** absolute path to the PDF
**Output:** `{ diagram_page_index, bom_page_index, classification_confidence }`

Three strategies tried in order:

1. **pdfplumber table detection** — counts table cells per page. Page with the most cells (≥ `PAGE_CLASSIFIER_MIN_TABLE_CELLS=4`) becomes the BOM candidate.
2. **PyMuPDF path density** — counts vector drawing paths per page. Page with the most paths (that isn't the BOM page) becomes the diagram candidate.
3. **Positional fallback** — if no table detected above threshold, page 0 = diagram, last page = BOM. Sets `confidence = "low"`.

**Tested result (Bobcat PDF):**
```python
{ "diagram_page_index": 0, "bom_page_index": 1, "classification_confidence": "high" }
```

---

### `image_preprocessor.py` — How It Works

**Input:** BGR image (np.ndarray) rendered from the diagram page
**Output:** binary image ready for `cv2.findContours`

Six steps in order:
1. **Grayscale** — reduce 3-channel BGR to single-channel
2. **Gaussian blur** — kernel `(3,3)`, suppresses rendering artifacts
3. **CLAHE** — clip `2.0`, tile `8×8`, normalises contrast across diagram regions
4. **Otsu threshold** — `THRESH_BINARY_INV` → white edges on black background (what findContours expects)
5. **Morphological closing** — elliptical kernel `(3,3)`, fills gaps in circle boundaries
6. **Deskew** — corrects rotation if skew > `0.5°`. Capped at ±10° to reject detection failures (engineering PDFs rendered at 300 DPI are always 0° skew; this guard exists for scanned PDFs)

**Tested result (Bobcat PDF):**
```
Input: 2481×3508 px | Output: (3508, 2481) uint8 | Non-zero pixels: 170,761 | Time: ~130ms
```

**Known fix applied:** OpenCV 4.5+ changed `minAreaRect` to return angles in `(-90°, 90°]` instead of `[-90°, 0°)`. Without the ±10° cap, the deskew incorrectly rotated the image by 89.95°. Cap added.

---

### `circle_detector.py` — How It Works

**Input:** binary image from `image_preprocessor`
**Output:** `list[{ x, y, radius }]` — pixel coordinates of detected circles

Algorithm:
1. `cv2.findContours` with `RETR_LIST` — finds all contour shapes
2. For each contour: compute **circularity** = `4π·area / perimeter²` (1.0 = perfect circle)
3. Keep only contours where circularity ≥ `0.75` AND radius is within `[12, 80]` px
4. Get circle centre and radius via `cv2.minEnclosingCircle`
5. **Deduplicate** — if two circle centres are closer than the larger radius, keep the bigger one

**Tested result (Bobcat PDF):**
```
410 raw contours → 176 too small, 10 too large, 196 not circular → 20 accepted
```

**Key finding:** The 20 detected circles are **mechanical drawing features** (bolt holes, section marks, title block symbols) — NOT callout bubbles. The Bobcat PDF uses plain text callout numbers with leader lines, not encircled numbers. Circle detection is retained for PDFs that do use circled callouts.

---

### `callout_reader.py` — How It Works

**Input:** diagram image, circles list, PyMuPDF page object, scale factor
**Output:** `list[{ x, y, radius, number, extraction_method }]`

Two strategies tried in order:

**Strategy A — PyMuPDF full-page text scan (fast)**
Reads all text spans from the PDF's text layer. Keeps only standalone 1–2 digit tokens. Returns pixel coordinates by converting PDF points via `PDF_RENDER_DPI / 72`.

**Why Strategy A returns 0 on the Bobcat PDF:** The diagram page is a 600×878 JPEG raster image embedded in the PDF. The callout numbers are burned into the JPEG pixels — they are NOT PDF text operators. PyMuPDF's text layer contains only the title block text (one Roboto-Regular font, 0 XObjects, 0 annotations). Strategy A correctly returns 0; it is not broken.

**Strategy B — Full-image PaddleOCR with two passes (fallback)**

*Pass 1: Overlapping horizontal tiles*
Splits the 2481×3508 image into 3 horizontal tiles (~1461px tall, 25% overlap). Runs PaddleOCR on each tile. Keeps the highest-confidence detection per unique number across all tiles.

*Pass 2: Seed-expansion*
For every callout found in Pass 1 (a "seed"), crops a 350px radius region around it and re-runs OCR with a lower confidence threshold (0.40 vs 0.50). Catches adjacent digits clustered near an already-detected number that the broad tile scan misses due to detection window interference. Upscales crops smaller than 150px before OCR.

Key PaddleOCR settings:
- `det_limit_side_len=3600` — prevents internal downscaling of our 3508px image (default 960 shrinks callout numbers to ~11px, making them undetectable)
- `det_db_thresh=0.2` — more aggressive text region detection than default 0.3
- `_clean(text)` — strips leading AND trailing non-digit characters: `"-6"` → `"6"`, `"10-"` → `"10"`, `"-13-"` → `"13"`

**No fabricated coordinates:** Callouts not detected in either pass are simply absent from the returned list. They surface as `unmappedBomRows` in the final result. The codebase never assigns `(0, 0)` or placeholder positions to undetected callouts.

**Tested result (Bobcat PDF):**
```
Pass 1: Found 12/17 — [1, 2, 3, 5, 10, 11, 12, 13, 14, 15, 16, 17]
Pass 2: 0 new callouts (seed-expansion added nothing)
Missing: 4, 6, 7, 8, 9
Time: ~22 seconds (PaddleOCR cold start included)
```

**Known limitation — missing callouts 4, 6, 7, 8, 9:**
- These 5 callouts are absent from both Pass 1 and Pass 2, meaning they are in regions PaddleOCR cannot detect at this JPEG source quality.
- Pass 2 finding 0 new callouts confirms they are not clustered near any of the 12 found seeds — they are either isolated in the diagram or in a compressed JPEG region below PaddleOCR's detection threshold.
- OCR engineering measures tried: `det_limit_side_len=3600`, `det_db_thresh=0.2`, overlapping tiles, seed-expansion, leader-line prefix/suffix stripping. None resolved these 5.
- Resolution: reported as `unpositionedBomRows` in result. Gemini sees them in the LLM validation input but is explicitly instructed not to invent coordinates for them.

---

### `bom_extractor.py` — How It Works

**Input:** PDF path, BOM page index
**Output:** `list[{ ref_no, part_no, description, qty }]`

**Strategy A — pdfplumber table extraction (primary)**
Uses pdfplumber's automatic table detection. Takes the largest table on the page (by row count). Detects column positions from the header row using keyword matching.

Header detection fixes applied:
- Normalise header text with `re.sub(r"[\s\-]+", "", cell.strip().lower())` before keyword matching. Required to match `"Q-\nty"` → `"qty"` (pdfplumber splits wrapped text with `\n`).
- `_is_header_row()` only checks the first cell. Previously checked all cells, causing rows with `"Ref."` in the description (e.g., `"CYL ASSY S100 TILT, Ref. 2-16"`) to be falsely identified as header rows and skipped.
- First cell starting with a digit always returns `False` from `_is_header_row()` — data rows always start with the ref number.

**Strategy B — PaddleOCR (scanned PDFs fallback)**
Renders the BOM page at `PDF_RENDER_DPI`, runs OCR, clusters text spans by Y-coordinate (gap > 20px = new row), assigns columns by X-band from the widest detected row (assumed header).

**Tested result (Bobcat PDF):**
```
18 BOM rows extracted, all qty fields populated
Strategy: pdfplumber (Strategy A)
```

---

### `mapping_engine.py` — How It Works

**Input:** callouts list (from callout_reader), BOM rows list (from bom_extractor)
**Output:** `{ mappings, unmapped_hotspots, unpositioned_bom_rows }`

Three stages:
1. **Normalise** — strip leading zeros, strip whitespace from both sides
2. **Exact match** — claims ALL unclaimed BOM rows sharing the same ref (handles duplicates like ref 11 appearing twice — both rows land in one mapping's `bom[]` array)
3. **Fuzzy match** — Levenshtein edit distance ≤ `MAPPING_MAX_EDIT_DISTANCE=1`; only the single best row is claimed (multi-row fuzzy claiming is semantically unsound)

**Output structure — one mapping object per hotspot, `bom[]` always an array:**
```python
{
    "hotspot_number": "11",
    "x": 1114, "y": 1784, "radius": 17,
    "confidence": 1.0,
    "bom": [
        { "ref_no": "11", "part_no": "6812170", "description": "PLUG HYD TUBE", "qty": 2 },
        { "ref_no": "11", "part_no": "75K3",    "description": "O-RING",         "qty": 2 },
    ]
}
```

**Semantic distinction:**
- `unmapped_hotspots` — hotspot detected on diagram, no BOM row found
- `unpositioned_bom_rows` — BOM row exists, but OCR never detected a callout for it (refs 4, 6, 7, 8, 9 on Bobcat). These are NOT "unmapped" — they simply have no detected diagram position.

**Tested result (Bobcat PDF, post-Milestone 2D refactor):**
```
12 callouts → 12 mappings (all exact match)
  - hotspot 11 → bom: [PLUG HYD TUBE, O-RING] (two rows, one mapping)
0 unmapped hotspots
5 unpositioned BOM rows (refs 4, 6, 7, 8, 9)
```

---

### `result_writer.py` — How It Works

**Input:** all pipeline outputs including `llm_validations`
**Output:** writes `<job_output_dir>/result.json`, returns the path

Converts Python snake_case field names to camelCase at the serialisation boundary. Fields written:

```json
{
  "diagramImagePath": "outputs/<jobId>/diagram.png",
  "imageWidth": 2481,
  "imageHeight": 3508,
  "processingDurationMs": 29457,
  "pageMap": { "diagramPageIndex": 0, "bomPageIndex": 1, "classificationConfidence": "high" },
  "hotspots": [ { "number", "x", "y", "radius", "extractionMethod" } ],
  "bom": [ { "refNo", "partNo", "description", "qty" } ],
  "mappings": [ { "hotspotNumber", "x", "y", "radius", "confidence", "bom": [...] } ],
  "unmappedHotspots": [],
  "unpositionedBomRows": [ { "refNo", "partNo", "description", "qty" } ],
  "llmValidations": []
}
```

**Tested result:** 8,264 bytes written to `storage/outputs/<job_id>/result.json`

---

## Milestones Remaining

| Milestone | Description | Status |
|---|---|---|
| 2C | Backend ↔ Python integration test via Postman (real PDF → Node.js → result) | ✅ Complete |
| 2D | Gemini 2.5 Flash LLM validation layer | ✅ Implementation complete · end-to-end test pending |
| 3 | React frontend — diagram viewer + BOM table overlay | ⏳ After 2D |
| 4 | Production hardening (Cloudinary, rate limiting, deploy) | ⏳ Last |

---

## Key Design Decisions (ADR Summary)

| Decision | Choice | Why |
|---|---|---|
| Node↔Python communication | CLI subprocess + stdout JSON lines | Simple, no message broker needed, readline handles backpressure |
| Callout detection (Bobcat PDF) | Full-image PaddleOCR with tiling | Callout numbers are pixel art in a JPEG — no text layer; PyMuPDF correctly returns 0 |
| Circle detection algorithm | `findContours` + circularity ratio | More robust than HoughCircles for engineering drawings; no false positives from hatching |
| OCR scale fix | `det_limit_side_len=3600` | Default 960 downscales 3508px image to 11px callout numbers — undetectable |
| OCR tiling | 3 overlapping horizontal strips + seed-expansion pass | Tiles fix tile-boundary misses; seed-expansion catches clustered digits |
| OCR text cleaning | Strip leading AND trailing non-digits | Leader lines produce `"-6"` or `"10-"` tokens; both ends must be stripped |
| Undetected callouts | Absent from result (no fabricated coordinates) | `(0, 0)` would mislead the frontend into rendering pins at the top-left corner |
| Mapping structure | One mapping per hotspot; `bom[]` always an array | Handles duplicate BOM refs (e.g. ref 11 = two rows) without splitting the hotspot |
| Semantic naming: unpositionedBomRows | BOM rows whose callout was never detected by OCR | "Unmapped" implies a failed search; these rows exist, they just have no diagram position |
| Artifact-relative diagram path | Python writes `outputs/<jobId>/diagram.png`; Node transforms to `/static/...` | Keeps Python unaware of HTTP; Node owns the URL namespace |
| LLM role | Semantic reasoning only — never geometry | Gemini 2.5 Flash validates fuzzy mappings and flags anomalies; never performs OCR or assigns coordinates |
| Gemini integration | REST API via `requests`, not `google-generativeai` SDK | `paddlepaddle==2.6.2` requires `protobuf<=3.20.2`; the SDK upgrades to 5.x — incompatible on Windows |
| LLM failure handling | Any exception → `llm_validations: []`, pipeline continues | LLM is advisory, not load-bearing; deterministic results must always be returned |
| MongoDB hosting | Atlas (not local) | No local install; free tier sufficient for development |
| Storage | Local filesystem (not Cloudinary) | Cloudinary deferred to Milestone 4 |
| Missing callouts (4,6,7,8,9) | Reported as `unpositionedBomRows` | PaddleOCR detection limit on compressed JPEG; Gemini sees them but is instructed not to invent coordinates |
| File cleanup | Keep `diagram.png` + `result.json`, delete `preprocessed.png` + source PDF | Frontend needs diagram; source PDF not needed after processing |

---

## Milestone 2C — Integration Test ✅ COMPLETE

End-to-end test: `POST /api/upload` (real Bobcat PDF via Postman) → Python spawns → MongoDB updated → `GET /api/results/:jobId` returns correct JSON.

**Bugs found and fixed during 2C:**

1. **`main.py` calling `read_callouts()` with stale 5-argument signature** — old call passed `bom_ref_numbers` which was removed when Pass 3 (BOM cross-reference) was rejected. Fixed by removing the early BOM extraction block and updating to 4-argument call.

2. **`PYTHON_EXECUTABLE=python` spawning system Python** — system Python has none of the pipeline deps. Fixed by setting `PYTHON_EXECUTABLE=D:\ExplodedView\ai-worker\venv\Scripts\python.exe` in `backend/.env`. `config.js` updated to detect path separators and resolve the executable relative to `backend/`.

3. **No `cwd` on spawn — Python can't resolve relative imports** — Without `cwd`, Python ran from the Node.js working directory and `from config import ...` failed. Fixed by adding `cwd: path.dirname(config.python.workerPath)` to spawn options in `python.bridge.js`.

4. **Mongoose validation errors — Python wrote snake_case, schema expected camelCase** — `result_writer.py` was emitting `ref_no`, `extraction_method`, etc. directly. Fixed by adding explicit serialiser helpers that map all field names at the serialisation boundary.

5. **Unicode `→` crashing Python logger on Windows** — Windows console uses cp1252 which can't encode U+2192. Fixed by replacing `→` with `->` in two `logger.info` lines in `main.py`.

**Final GET /api/results response verified:**
```json
{
  "mappings": 12,
  "unmappedHotspots": 0,
  "unpositionedBomRows": 5,
  "diagramImagePath": "/static/outputs/<jobId>/diagram.png"
}
```

---

## Milestone 2D — LLM Validation Layer ✅ Implementation complete · end-to-end test pending

### What was built

**`llm_resolver.py`** — Full Gemini 2.5 Flash integration replacing the stub.

- Called only when fuzzy mappings (confidence < 1.0) OR unmapped hotspots exist. Bobcat PDF's all-exact-match result skips LLM entirely.
- Uses `requests.post()` to `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}` — no SDK.
- Payload uses `responseMimeType: "application/json"` to get structured output directly.
- Output: flat list of dicts with `type` key: `fuzzy_validation`, `hotspot_suggestion`, `consistency_flag`.
- Any exception → returns `{...mapping_result, "llm_validations": []}`. Pipeline never crashes.

**`mapping_engine.py`** — Rewritten for Milestone 2D schema:
- `_find_all_matches()` returns `(list[int], float)` — exact match claims ALL unclaimed rows with same ref (handles ref 11 → two BOM rows).
- Output key renamed: `unmapped_bom_rows` → `unpositioned_bom_rows`.
- One mapping per hotspot, `bom: [...]` always an array.

**`result_writer.py`** — Updated serialisation:
- Accepts `unpositioned_bom_rows` and `llm_validations` parameters.
- `diagram_image_path` is passed as artifact-relative; result.json writes `outputs/<jobId>/diagram.png`.
- Node bridge (`python.bridge.js`) prepends `/static/` before persisting to MongoDB.

**`Result.model.js`** — Schema updated:
- `MappingSchema` now: `{ hotspotNumber, x, y, radius, confidence, bom: [BomRowSchema] }`
- `unmappedBomRows` → `unpositionedBomRows`
- `llmValidations: { type: Array, default: [] }`

**`ai-worker/.env`** — Created:
```
STORAGE_PATH=../storage
PDF_RENDER_DPI=300
GEMINI_API_KEY=AIzaSy...
GEMINI_MODEL=gemini-2.5-flash
LLM_TIMEOUT_SECONDS=15
LLM_ENABLED=false
DEBUG=false
```

### Protobuf conflict resolution

Installing `google-generativeai` upgrades `protobuf` from `3.20.2` to `5.x`, breaking `paddlepaddle==2.6.2` on Windows. Resolution: uninstall all google packages, keep `protobuf==3.20.2`, and call Gemini via plain HTTP.

Uninstall command (run once in the venv):
```
pip uninstall google-generativeai google-ai-generativelanguage google-api-python-client google-auth-httplib2 httplib2 uritemplate grpcio grpcio-status proto-plus googleapis-common-protos google-api-core -y
```

### LLM strict contract

| What Gemini IS responsible for | What Gemini is NOT allowed to do |
|---|---|
| Validate fuzzy mappings (confidence < 1.0) | Read callout numbers from the diagram image |
| Flag consistency anomalies across confirmed mappings | Generate or modify (x, y) coordinates |
| Suggest BOM refs for unmapped hotspots (with low confidence) | Override exact matches (confidence == 1.0) |
| | Claim to have found callouts OCR missed |
