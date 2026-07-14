# Engineering PDF Analyzer — System Design Document

**Project:** AI-Powered Exploded-View PDF Analyzer
**Version:** 2.0 (Architecture Revision)
**Date:** 2026-07-14
**Stack:** Node.js + Express · React · MongoDB · Python · OpenCV · PaddleOCR
**Deadline:** 2 days (MVP)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Core Philosophy](#2-core-philosophy)
3. [High-Level Architecture](#3-high-level-architecture)
4. [Module Breakdown](#4-module-breakdown)
5. [Folder Structure](#5-folder-structure)
6. [Module Responsibilities](#6-module-responsibilities)
7. [Processing Pipeline](#7-processing-pipeline)
8. [Node.js ↔ Python Communication](#8-nodejs--python-communication)
9. [Database Schema](#9-database-schema)
10. [API Endpoints](#10-api-endpoints)
11. [File Lifecycle Management](#11-file-lifecycle-management)
12. [Development Milestones](#12-development-milestones)
13. [Architecture Decision Log](#13-architecture-decision-log)

---

## 1. Project Overview

The system processes mechanical engineering PDFs that contain:

- **Exploded-view assembly diagrams** — technical drawings with numbered callout circles pointing to individual parts
- **Bill of Materials (BOM) tables** — structured tables listing Ref Number, Part Number, Description, Quantity, and related fields

The pipeline automatically:
1. Classifies which pages contain diagrams vs BOM tables
2. Preprocesses diagram images for robust computer vision
3. Detects callout circle geometry via contour analysis
4. Extracts numbers from callouts using PaddleOCR (with direct PDF text extraction preferred when available)
5. Parses the BOM table into structured rows
6. Maps each hotspot number to its BOM entry with fuzzy tolerance
7. Produces a structured JSON output with confidence scores and unmapped items
8. Visualizes results interactively in a React frontend

### Constraints

| Constraint | Decision |
|------------|----------|
| No model training | Pretrained / open-source / free tools only |
| Backend | Node.js + Express |
| Frontend | React |
| Database | MongoDB |
| CV / Processing | Python, OpenCV, PaddleOCR, PyMuPDF |
| LLM role | Semantic reasoning and validation only — not geometry detection |
| Timeline | 2-day MVP |

---

## 2. Core Philosophy

This is the guiding principle for every technical decision in this project:

```
Classical Computer Vision   →   Geometry and localization (circle detection, coordinates)
PyMuPDF / PaddleOCR         →   Text extraction from circles and BOM
Deterministic Mapping Engine →   Normalization, exact match, fuzzy match
LLM (optional layer)         →   Semantic reasoning, ambiguity resolution, validation
```

**Why this matters:**

Hotspot coordinates are the foundation of the interactive frontend overlay. They must be precise and deterministic. An LLM cannot reliably produce pixel-accurate coordinates, and should never be trusted to do so. Classical CV owns geometry. The LLM is invoked only after coordinates are confirmed, to reason about meaning — not location.

---

## 3. High-Level Architecture

```
┌────────────────────────────────────────────────────────────┐
│                      React Frontend                         │
│    Upload UI · Diagram Viewer · Interactive BOM Table      │
└──────────────────────────┬─────────────────────────────────┘
                           │ HTTP REST
┌──────────────────────────▼─────────────────────────────────┐
│                   Node.js / Express API                      │
│        Job orchestration · File handling · DB operations    │
└───────────┬───────────────────────────────┬────────────────┘
            │ child_process spawn            │ Mongoose ODM
┌───────────▼────────────┐      ┌───────────▼───────────────┐
│   Python CV Pipeline   │      │         MongoDB            │
│                        │      │  jobs · results            │
│  page_classifier       │      │                            │
│  image_preprocessor    │      └───────────────────────────┘
│  circle_detector       │
│  callout_reader        │      ┌───────────────────────────┐
│  bom_extractor         │      │    storage/ (shared)       │
│  mapping_engine        │      │  uploads/ · outputs/       │
│  result_writer         │      └───────────────────────────┘
└────────────────────────┘
```

**Node.js** is the orchestrator. It owns the job lifecycle and database state.
**Python** is a stateless processing pipeline. It reads from `storage/`, writes to `storage/`, and exits.
**`storage/`** is a shared top-level directory. Neither service owns files that the other needs to read.

---

## 4. Module Breakdown

### Python Pipeline Modules

| # | Module | Responsibility |
|---|--------|----------------|
| 1 | `page_classifier.py` | Identify which pages are diagrams vs BOM tables using structural heuristics |
| 2 | `image_preprocessor.py` | Prepare diagram image for CV: grayscale → blur → threshold → morph ops |
| 3 | `circle_detector.py` | Detect callout circle geometry using contour analysis + circularity filtering |
| 4 | `callout_reader.py` | Extract the number from each circle region via PyMuPDF text lookup or PaddleOCR |
| 5 | `bom_extractor.py` | Extract BOM table rows using pdfplumber (primary) or PaddleOCR (fallback) |
| 6 | `mapping_engine.py` | Normalize, match, and fuzzy-join hotspot numbers to BOM ref numbers |
| 7 | `result_writer.py` | Serialize final output to `result.json` |
| 8 | `main.py` | Entry point: parse CLI args, orchestrate all modules in sequence |

### Node.js Modules

| # | Module | Responsibility |
|---|--------|----------------|
| 9 | Upload Controller | Accept PDF, validate file type, save to `storage/uploads/`, create Job |
| 10 | Python Bridge | Spawn Python subprocess, stream stdout, handle completion and errors |
| 11 | Job Manager | Maintain job lifecycle state in MongoDB |
| 12 | Result Controller | Read Result from MongoDB, serve to frontend |
| 13 | Static File Server | Serve `storage/outputs/<jobId>/diagram.png` |
| 14 | Cleanup Service | Delete temp files after result is saved; enforce TTL on jobs |

---

## 5. Folder Structure

```
exploded-view/
│
├── storage/                              # Shared runtime data (not committed to git)
│   ├── uploads/                          # Uploaded PDFs, keyed by jobId
│   └── outputs/                          # Per-job processing outputs
│       └── <jobId>/
│           ├── diagram.png               # Extracted diagram page image
│           ├── preprocessed.png          # Preprocessed image (debug artifact)
│           └── result.json               # Final structured output
│
├── documentation/
│   └── system-design.md
│
├── backend/                              # Node.js + Express
│   ├── src/
│   │   ├── routes/
│   │   │   ├── upload.routes.js
│   │   │   └── jobs.routes.js
│   │   ├── controllers/
│   │   │   ├── upload.controller.js
│   │   │   └── jobs.controller.js
│   │   ├── services/
│   │   │   ├── python.bridge.js          # Spawn Python, stream stdout, read result
│   │   │   └── cleanup.service.js        # File + DB lifecycle management
│   │   ├── models/
│   │   │   ├── Job.model.js
│   │   │   └── Result.model.js
│   │   └── app.js
│   ├── .env                              # STORAGE_PATH, MONGO_URI, etc.
│   └── package.json
│
├── ai-worker/                            # Python CV pipeline
│   ├── main.py                           # CLI entry point
│   ├── modules/
│   │   ├── page_classifier.py
│   │   ├── image_preprocessor.py
│   │   ├── circle_detector.py
│   │   ├── callout_reader.py
│   │   ├── bom_extractor.py
│   │   ├── mapping_engine.py
│   │   └── result_writer.py
│   ├── config.py                         # Shared constants: DPI, thresholds, paths
│   └── requirements.txt
│
└── frontend/                             # React
    ├── src/
    │   ├── components/
    │   │   ├── UploadForm.jsx
    │   │   ├── DiagramViewer.jsx         # Renders PNG + SVG hotspot overlays
    │   │   └── BOMTable.jsx              # Highlights row on hotspot hover
    │   ├── pages/
    │   │   ├── UploadPage.jsx
    │   │   └── ResultPage.jsx
    │   └── App.jsx
    └── package.json
```

**Key structural decisions:**
- `storage/` is at root level, shared by both Node.js and Python via the `STORAGE_PATH` env var
- `ai-worker/config.py` holds all tunable constants — DPI, circularity threshold, blur kernel size — so they are never buried in individual modules
- `preprocessed.png` is saved as a debug artifact during development; excluded in production via a `DEBUG` flag in `config.py`

---

## 6. Module Responsibilities

---

### `page_classifier.py`

**Input:** list of `pymupdf` page objects from the loaded PDF

**Strategy:**
- For each page, call `pdfplumber.page.extract_tables()`
  - If structured tables are detected → BOM candidate
- Measure the ratio of vector paths (lines, curves) to text blocks using `pymupdf` page analysis
  - High path density + low structured text → diagram candidate
- Return: `{ diagramPageIndex: int, bomPageIndex: int }`

**Fallback:** If classification is ambiguous, default to the last page as BOM and the first content page as diagram, and flag the job with `classificationConfidence: "low"`.

---

### `image_preprocessor.py`

**Input:** `diagram.png` (high-res, rendered at 300 DPI by PyMuPDF)

**Processing steps in order:**

| Step | Operation | Purpose |
|------|-----------|---------|
| 1 | `cv2.cvtColor → GRAY` | Remove color channels before analysis |
| 2 | `cv2.GaussianBlur(3×3)` | Suppress rendering artifacts and minor noise |
| 3 | CLAHE (`clipLimit=2.0`) | Normalize contrast across diagram regions |
| 4 | Otsu's threshold | Convert to binary image for contour detection |
| 5 | Morphological closing (`3×3 kernel`) | Close small gaps in circle boundaries |
| 6 | (Optional) Deskew | Detect and correct rotation via Hough line angle; only applied if skew > 0.5° |

**Output:** `preprocessed.png` (binary or enhanced grayscale, ready for `circle_detector.py`)

**Note:** Preprocessing parameters are defined in `config.py`. No hardcoded magic numbers inside this module.

---

### `circle_detector.py`

**Input:** `preprocessed.png`

**Strategy: Contour-based detection with circularity filtering**

```
1. cv2.findContours on the preprocessed binary image
2. For each contour:
   a. Compute area = cv2.contourArea(contour)
   b. Compute perimeter = cv2.arcLength(contour, closed=True)
   c. Compute circularity = (4π × area) / (perimeter²)
   d. Filter: circularity > CIRCULARITY_THRESHOLD (default 0.75)
   e. Filter: radius within [MIN_RADIUS, MAX_RADIUS] defined in config.py
3. For surviving contours, compute enclosing circle: cv2.minEnclosingCircle
4. Output: list of { x, y, radius } in pixel coordinates
```

**Why contour + circularity over HoughCircles:**
- HoughCircles is gradient-based and designed for photographic images
- Vector PDF callout circles rendered to PNG have crisp binary edges — contour detection is more precise and stable on these
- Circularity ratio filtering is a parameter, not a tuning exercise across 4+ interdependent parameters

**Output:** `[{ x: int, y: int, radius: int }]`

---

### `callout_reader.py`

**Input:** original `diagram.png` + list of circle geometries from `circle_detector.py`

**Two-strategy extraction (in order of priority):**

**Strategy A — Direct PyMuPDF text extraction (vector PDFs):**
- For each circle `(x, y, radius)`, define a bounding rectangle in PDF coordinate space
- Query `page.get_text("words", clip=rect)` to find text objects within that region
- If text is found with confidence → use it directly, no OCR needed

**Strategy B — PaddleOCR fallback (scanned or image-based PDFs):**
- Crop the circle region from `diagram.png` with a small padding margin
- Upscale the crop to at least 64×64 px before OCR (small crops fail OCR)
- Run PaddleOCR with `use_angle_cls=False`, `lang='en'`
- Filter results to numeric characters only

**Why PaddleOCR over Tesseract:**
- PaddleOCR is significantly more accurate on small, isolated numeric text
- Does not require per-call PSM configuration flags to behave correctly on digits
- Handles slightly degraded or compressed PDF renders better than Tesseract
- No `--psm` tuning required; digit-only filtering is applied post-OCR on the result text

**Output:** `[{ x, y, radius, number: string, extractionMethod: "pymupdf" | "paddleocr" }]`

---

### `bom_extractor.py`

**Input:** `pymupdf` page object for the BOM page

**Strategy A — pdfplumber (selectable text PDFs):**
- `page.extract_tables()` returns a 2D list of cell values
- Parse headers to identify columns: Ref No, Part No, Description, Qty
- Clean cells: strip whitespace, normalize empty strings to null

**Strategy B — PaddleOCR (scanned / image-based PDFs):**
- Render BOM page to PNG at 300 DPI
- Run PaddleOCR to extract text blocks with bounding boxes
- Reconstruct table rows by clustering text blocks on the same horizontal band (Y-coordinate proximity)
- Map clusters to columns by X-coordinate ranges

**Output:** `[{ refNo, partNo, description, qty }]`

---

### `mapping_engine.py`

**Input:** hotspot list (with numbers) + BOM rows

**Three-stage matching pipeline:**

```
Stage 1 — Normalize both sides:
  - Strip leading zeros:  "03" → "3"
  - Uppercase:            "a1" → "A1"
  - Strip whitespace and punctuation

Stage 2 — Exact match:
  - Direct lookup: hotspot.number == bom.refNo (after normalization)
  - Mark matched pairs with confidence: 1.0

Stage 3 — Fuzzy match (for unresolved hotspots):
  - Compute Levenshtein edit distance between hotspot.number and each unmatched bom.refNo
  - Accept match if edit_distance == 1
  - Mark matched pairs with confidence: 0.7
  - This handles: "1B" → "13", "O5" → "05" (common OCR errors)

Collect leftovers:
  - unmappedHotspots: hotspots that found no BOM match in any stage
  - unmappedBomRows: BOM rows that no hotspot claimed
```

**Output:** `{ mappings, unmappedHotspots, unmappedBomRows }`

---

### `result_writer.py`

**Input:** all processed data from upstream modules

**Responsibility:** single output contract — assembles and serializes `result.json`. No logic. No decisions. Only serialization.

---

### `main.py`

**CLI interface:**

```
python main.py --job-id <uuid> --storage-path <path>
```

**Orchestration sequence:**
1. Load PDF from `storage/uploads/<jobId>.pdf`
2. `page_classifier` → identify diagram page and BOM page
3. `pdf_splitter` (inline, via PyMuPDF) → render diagram page to `storage/outputs/<jobId>/diagram.png`
4. `image_preprocessor` → produce `preprocessed.png`
5. `circle_detector` → detect circle geometries
6. `callout_reader` → extract numbers from circles
7. `bom_extractor` → extract BOM rows
8. `mapping_engine` → produce mappings + unmapped lists
9. `result_writer` → write `result.json`
10. Print `{"status": "done"}` to stdout

On any unhandled exception: print `{"status": "error", "message": "<msg>"}` and exit with code 1.

---

## 7. Processing Pipeline

```
[User uploads PDF]
        │
        ▼
[Node.js: save to storage/uploads/<jobId>.pdf]
[MongoDB: Job created — status: "pending"]
        │
        ▼
[Node.js: spawn Python subprocess]
[MongoDB: Job status → "processing"]
        │
        ▼
┌───────────────────────────────────────────────┐
│              Python Pipeline                   │
│                                               │
│  1. page_classifier                           │
│     Heuristic detection of diagram + BOM page │
│              │                                │
│  2. PyMuPDF render                            │
│     Diagram page → diagram.png (300 DPI)      │
│              │                                │
│  3. image_preprocessor                        │
│     grayscale → blur → CLAHE                  │
│     → threshold → morph → preprocessed.png    │
│              │                    │           │
│  4. circle_detector    5. bom_extractor       │
│     findContours +        pdfplumber (A)      │
│     circularity filter    PaddleOCR (B)       │
│     → [{x,y,radius}]     → [{refNo,...}]      │
│              │                    │           │
│  6. callout_reader                │           │
│     PyMuPDF text (A)              │           │
│     PaddleOCR crop (B)            │           │
│     → [{x,y,radius,number}]       │           │
│              │                    │           │
│              └──────────┬─────────┘           │
│                         ▼                     │
│               7. mapping_engine               │
│                  normalize → exact match      │
│                  → fuzzy match → leftovers    │
│                         │                     │
│               8. result_writer                │
│                  → result.json                │
└───────────────────────────────────────────────┘
        │
        ▼
[Node.js: reads result.json]
[MongoDB: Result saved, Job status → "done"]
[Node.js: cleanup.service deletes temp files]
        │
        ▼
[Frontend polls /api/jobs/:jobId → status: done]
[Frontend fetches /api/results/:jobId]
[React: renders diagram.png + SVG hotspot overlays + BOM table]
```

---

## 8. Node.js ↔ Python Communication

**Mechanism:** `child_process.spawn` (CLI subprocess)

```
Node.js spawns:
  python main.py --job-id abc123 --storage-path /app/storage

Python reads:
  /app/storage/uploads/abc123.pdf

Python writes:
  /app/storage/outputs/abc123/diagram.png
  /app/storage/outputs/abc123/result.json

Python signals via stdout (newline-delimited JSON):
  {"status": "processing", "step": "page_classification"}
  {"status": "processing", "step": "circle_detection"}
  {"status": "done"}
  {"status": "error", "message": "No BOM table found on any page"}

Node.js behaviour:
  - Each stdout line → update Job.currentStep in MongoDB (optional for progress UI)
  - On "done" → read result.json → save Result → update Job status
  - On "error" → update Job status to "error" + store errorMessage
  - On process exit code 1 with no stdout → treat as unknown error
```

**Why CLI subprocess over Python HTTP server:**
Avoids port management, process supervision, and startup race conditions. Sufficient for MVP concurrency (each job is one subprocess). Each Python process is fully isolated.

---

## 9. Database Schema

### Jobs Collection

```json
{
  "_id": "ObjectId",
  "jobId": "string (uuid v4)",
  "filename": "string",
  "status": "pending | processing | done | error",
  "currentStep": "string | null",
  "errorMessage": "string | null",
  "createdAt": "Date",
  "updatedAt": "Date"
}
```

TTL index: `createdAt` expires after **7 days** (MongoDB TTL index, defined on Job model).

---

### Results Collection

```json
{
  "_id": "ObjectId",
  "jobId": "string",
  "diagramImagePath": "string",
  "imageWidth": "number (pixels)",
  "imageHeight": "number (pixels)",
  "processingDurationMs": "number",
  "pageMap": {
    "diagramPageIndex": "number",
    "bomPageIndex": "number",
    "classificationConfidence": "high | low"
  },
  "hotspots": [
    {
      "number": "string",
      "x": "number",
      "y": "number",
      "radius": "number",
      "extractionMethod": "pymupdf | paddleocr"
    }
  ],
  "bom": [
    {
      "refNo": "string",
      "partNo": "string",
      "description": "string",
      "qty": "number"
    }
  ],
  "mappings": [
    {
      "hotspotNumber": "string",
      "x": "number",
      "y": "number",
      "radius": "number",
      "refNo": "string",
      "partNo": "string",
      "description": "string",
      "qty": "number",
      "confidence": "number (0.0–1.0)"
    }
  ],
  "unmappedHotspots": [
    {
      "number": "string",
      "x": "number",
      "y": "number",
      "radius": "number"
    }
  ],
  "unmappedBomRows": [
    {
      "refNo": "string",
      "partNo": "string",
      "description": "string",
      "qty": "number"
    }
  ],
  "createdAt": "Date"
}
```

**Key additions over v1:**
- `imageWidth` / `imageHeight` — required by frontend to correctly scale SVG hotspot overlays
- `confidence` per mapping — enables frontend to visually flag uncertain matches
- `unmappedHotspots` / `unmappedBomRows` — visibility into what the pipeline could not resolve
- `pageMap` — records which pages were used and how confident the classification was
- `processingDurationMs` — basic observability

---

## 10. API Endpoints

| Method | Endpoint | Description | Request | Response |
|--------|----------|-------------|---------|----------|
| `POST` | `/api/upload` | Upload PDF, validate, create job, trigger pipeline | `multipart/form-data: file` | `{ jobId, status }` |
| `GET` | `/api/jobs/:jobId` | Poll job status and current step | — | `{ jobId, status, currentStep, errorMessage }` |
| `GET` | `/api/results/:jobId` | Fetch full result document | — | Full Result document |
| `GET` | `/api/diagram/:jobId` | Serve diagram PNG as static asset | — | `image/png` |

**Upload validation (Node.js):**
- File must have `.pdf` extension and `application/pdf` MIME type
- Reject before spawning Python — do not let the pipeline fail on an invalid file

---

## 11. File Lifecycle Management

### Temporary File Cleanup

After `result.json` is successfully read and saved to MongoDB:

```
DELETE: storage/uploads/<jobId>.pdf       ← raw PDF no longer needed
DELETE: storage/outputs/<jobId>/preprocessed.png   ← debug artifact
KEEP:   storage/outputs/<jobId>/diagram.png         ← served to frontend
KEEP:   storage/outputs/<jobId>/result.json         ← accessed during session
```

Cleanup is performed by `cleanup.service.js` immediately after the Result is saved to MongoDB.

### Long-Term Expiry

- MongoDB TTL index on `Jobs.createdAt`: **7 days**
- When a Job document is expired by MongoDB, a Node.js scheduled check (or pre-query hook) deletes the corresponding `storage/outputs/<jobId>/` directory
- This prevents unbounded disk growth without requiring an external cron job

---

## 12. Development Milestones

### Day 1 — Core Pipeline

| # | Task | Owner |
|---|------|-------|
| 1 | Scaffolding: folder structure, git, .env, `storage/` dirs | All |
| 2 | Node: Multer upload + PDF validation + Job model | Backend |
| 3 | Python: `config.py` with all tunable constants | Python |
| 4 | Python: `page_classifier.py` — heuristic page detection | Python |
| 5 | Python: `image_preprocessor.py` — full preprocessing chain | Python |
| 6 | Python: `circle_detector.py` — contour + circularity filter | Python |
| 7 | Python: `callout_reader.py` — PyMuPDF (A) + PaddleOCR (B) | Python |
| 8 | Python: `bom_extractor.py` — pdfplumber (A) + PaddleOCR (B) | Python |
| 9 | Python: `mapping_engine.py` — normalize + exact + fuzzy | Python |
| 10 | Python: `result_writer.py` + `main.py` wiring | Python |
| 11 | Node: `python.bridge.js` — spawn, stdout stream, result read | Backend |
| 12 | Node: Save Result to MongoDB, status endpoints | Backend |

### Day 2 — Frontend + Integration

| # | Task | Owner |
|---|------|-------|
| 13 | React: Upload form + polling loop for job status | Frontend |
| 14 | React: `DiagramViewer.jsx` — image + SVG overlay layer | Frontend |
| 15 | React: `BOMTable.jsx` — highlight row on hotspot hover | Frontend |
| 16 | React: Visual distinction for low-confidence mappings | Frontend |
| 17 | End-to-end test with a real engineering PDF | All |
| 18 | Node: `cleanup.service.js` — temp file deletion post-save | Backend |
| 19 | Error handling: bad PDF, no circles found, no BOM table | All |

---

## 13. Architecture Decision Log

Decisions recorded here to prevent revisiting settled questions during implementation.

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Circle detection | `findContours` + circularity ratio | More stable than HoughCircles on vector-rendered PNGs; single tunable threshold vs 4+ interdependent HoughCircles params |
| Primary text extraction | PyMuPDF direct (vector PDFs) | Zero OCR error risk when text is embedded; OCR is only invoked when necessary |
| OCR engine | PaddleOCR | Superior accuracy on small isolated numeric text vs Tesseract; no PSM flag configuration required |
| LLM role | Semantic layer only | Hotspot coordinates must be pixel-accurate and deterministic; LLMs cannot reliably produce spatial coordinates. LLM is reserved for ambiguity resolution on meaning, not geometry |
| Node↔Python bridge | CLI subprocess | Avoids second HTTP server; sufficient for MVP concurrency; fully isolated per job |
| Runtime storage | Top-level `storage/` | Decouples Node.js and Python from each other's directory trees; both services receive path via env var |
| Page detection | Heuristic classifier | No ML needed; pdfplumber table detection + path density ratio is sufficient and deterministic |
| Mapping | Normalize → exact → fuzzy (edit distance ≤ 1) | Handles common OCR substitution errors without introducing false positives from aggressive fuzzy matching |
| File cleanup | Post-save in Node.js | Keeps the Python pipeline stateless; cleanup is a Node.js responsibility as it owns the job lifecycle |
