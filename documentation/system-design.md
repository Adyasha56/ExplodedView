# Engineering PDF Analyzer — System Design Document

**Project:** AI-Powered Exploded-View PDF Analyzer
**Version:** 3.0 (Post Cloud Run Deployment)
**Date:** 2026-07-21
**Stack:** Node.js + Express · React · MongoDB · Python · OpenCV · PaddleOCR · Gemini Vision · Cloudinary · Google Cloud Run · Vercel

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Core Philosophy](#2-core-philosophy)
3. [High-Level Architecture](#3-high-level-architecture)
4. [Deployment Architecture](#4-deployment-architecture)
5. [Module Breakdown](#5-module-breakdown)
6. [Folder Structure](#6-folder-structure)
7. [Processing Pipeline](#7-processing-pipeline)
8. [Node.js ↔ Python Communication](#8-nodejs--python-communication)
9. [Database Schema](#9-database-schema)
10. [API Endpoints](#10-api-endpoints)
11. [File Lifecycle Management](#11-file-lifecycle-management)
12. [Architecture Decision Log](#12-architecture-decision-log)

---

## 1. Project Overview

The system processes mechanical engineering PDFs that contain:

- **Exploded-view assembly diagrams** — technical drawings with numbered callout circles pointing to individual parts
- **Bill of Materials (BOM) tables** — structured tables listing Ref Number, Part Number, Description, Quantity, and related fields

The pipeline automatically:
1. Classifies which pages contain diagrams vs BOM tables (multi-assembly aware)
2. Crops diagram to the drawing area, excluding title block and footer
3. Preprocesses diagram images for robust computer vision
4. Detects callout circle geometry — both dark-outlined and colored/filled circles
5. Extracts numbers from callouts via PyMuPDF text layer, PaddleOCR tile scan, per-circle OCR, and PaddleOCR per-circle recovery (Strategy D)
6. Recovers colored-circle refs using Gemini Vision multimodal API (Strategy E)
7. Parses the BOM table into structured rows
8. Maps each hotspot number to its BOM entry
9. Validates ambiguous mappings via Gemini text API (llm_resolver)
10. Uploads annotated diagram to Cloudinary
11. Saves structured JSON output to MongoDB
12. Visualizes results interactively in a React frontend

### Constraints

| Constraint | Decision |
|------------|----------|
| No model training | Pretrained / open-source / free tools only |
| Backend | Node.js + Express |
| Frontend | React |
| Database | MongoDB Atlas |
| CV / Processing | Python, OpenCV, PaddleOCR, PyMuPDF |
| LLM role | Semantic reasoning and vision recovery only — not geometry detection |
| Image hosting | Cloudinary |
| Deployment | Google Cloud Run (backend + Python worker), Vercel (frontend) |

---

## 2. Core Philosophy

```
Classical Computer Vision   →   Geometry and localization (circle detection, coordinates)
PyMuPDF / PaddleOCR         →   Text extraction from circles and BOM
Strategy D (PaddleOCR)      →   Per-circle recovery with multi-variant voting
Strategy E (Gemini Vision)  →   Colored-circle recovery when OCR fails
Deterministic Mapping Engine →   Normalization, exact match, fuzzy match
LLM (optional layer)         →   Semantic reasoning, ambiguity resolution, validation
```

**Why this matters:**

Hotspot coordinates are the foundation of the interactive frontend overlay. They must be precise and deterministic. An LLM cannot reliably produce pixel-accurate coordinates, and should never be trusted to do so. Classical CV owns geometry. Gemini Vision is invoked only to *read a number already positioned by CV* — it never generates coordinates. The LLM text layer is invoked only after coordinates are confirmed, to reason about meaning — not location.

**Accuracy over coverage:** An unpositioned BOM row is always preferable to a confidently wrong hotspot. This principle guides every fallback and recovery decision in the pipeline.

---

## 3. High-Level Architecture

```
┌────────────────────────────────────────────────────────────┐
│                      React Frontend                         │
│    Upload UI · Diagram Viewer · Interactive BOM Table      │
│    Deployed on: Vercel                                      │
└──────────────────────────┬─────────────────────────────────┘
                           │ HTTP REST
┌──────────────────────────▼─────────────────────────────────┐
│                   Node.js / Express API                      │
│        Job orchestration · File handling · DB operations    │
│    Deployed on: Google Cloud Run (asia-southeast1)          │
└───────┬───────────────────────┬────────────────────────────┘
        │ child_process spawn   │ Mongoose ODM
┌───────▼────────────┐   ┌─────▼──────────────────────────┐
│  Python CV Pipeline│   │         MongoDB Atlas            │
│  (same container)  │   │  jobs · results                 │
│                    │   └────────────────────────────────-─┘
│  page_classifier   │
│  image_preprocessor│   ┌────────────────────────────────┐
│  circle_detector   │   │    /tmp/explodedview-storage    │
│  callout_reader    │   │  (Cloud Run ephemeral storage)  │
│  strategy_d        │   │  uploads/ · outputs/            │
│  strategy_e        │   └────────────────────────────────┘
│  bom_extractor     │
│  mapping_engine    │   ┌────────────────────────────────┐
│  llm_resolver      │   │         Cloudinary              │
│  result_writer     │   │  Diagram PNG hosting            │
└────────────────────┘   └────────────────────────────────┘
```

**Node.js** is the orchestrator. It owns the job lifecycle and database state.
**Python** is a stateless processing pipeline. It runs inside the same Cloud Run container as Node.js, spawned as a subprocess.
**`/tmp/explodedview-storage/`** is the shared ephemeral directory on Cloud Run (local `storage/` in development). Neither service owns files that the other needs to read.
**Cloudinary** stores the annotated diagram PNG for serving to the frontend. Ephemeral Cloud Run storage cannot reliably serve files across requests.

---

## 4. Deployment Architecture

| Component | Platform | Region | Notes |
|-----------|----------|--------|-------|
| Frontend | Vercel | Auto (CDN) | React SPA, static hosting |
| Backend + Python | Google Cloud Run | asia-southeast1 | Node.js + Python in one container |
| Database | MongoDB Atlas | Auto | Shared cluster, connected via MONGO_URI |
| Image storage | Cloudinary | Auto (CDN) | Diagram PNG uploaded post-processing |

### Cloud Run Configuration

| Setting | Value |
|---------|-------|
| Memory | 2 GiB |
| CPU | 1 vCPU |
| Concurrency | 1 request per instance |
| Request timeout | 900s |
| Min instances | 0 (scales to zero) |
| Max instances | 2 |

**Why 2 GiB:** PaddleOCR loads model weights into memory. A full 3-tile scan of a 2481×2504px diagram reaches ~2100MB peak. Less memory causes OOM kills with no visible error.

**Why concurrency=1:** The Python pipeline is CPU-bound and single-threaded. Running two pipelines on one vCPU instance would cause both to timeout.

**Why scales to zero:** Cost efficiency for low-traffic usage. Cold start adds ~3–4s (Node.js init + MongoDB connect). PaddleOCR model load adds another ~13s on first OCR call per instance.

### Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `LLM_ENABLED` | Enable/disable Gemini calls (true/false) |
| `GEMINI_API_KEY` | Gemini REST API key |
| `GEMINI_MODEL` | Model name (e.g. `gemini-3.5-flash`) |
| `LLM_TIMEOUT_SECONDS` | Base timeout for Gemini calls |
| `CLOUDINARY_*` | Cloudinary upload credentials |
| `MONGO_URI` | MongoDB Atlas connection string |
| `STORAGE_PATH` | `/tmp/explodedview-storage` on Cloud Run |

---

## 5. Module Breakdown

### Python Pipeline Modules

| # | Module | Responsibility |
|---|--------|----------------|
| 1 | `page_classifier.py` | Identify which pages are diagrams vs BOM tables; supports multi-assembly PDFs |
| 2 | `image_preprocessor.py` | Prepare diagram image for CV: grayscale → blur → CLAHE → threshold → morph ops |
| 3 | `circle_detector.py` | Detect callout circles via contour analysis (dark-outlined) and HSV connected-components (colored/filled) |
| 4 | `callout_reader.py` | Extract callout numbers: Strategy A (PyMuPDF), Strategy B (PaddleOCR tile scan + seed expansion), Strategy C (per-circle OCR) |
| 5 | `strategy_d_recovery.py` | Per-circle PaddleOCR recovery with multi-variant preprocessing and majority voting |
| 6 | `strategy_e_recovery.py` | Gemini Vision multimodal recovery for colored circles OCR cannot read |
| 7 | `bom_extractor.py` | Extract BOM table rows using pdfplumber (primary) or PaddleOCR (fallback) |
| 8 | `mapping_engine.py` | Normalize, exact-match, and fuzzy-match hotspot numbers to BOM ref numbers |
| 9 | `llm_resolver.py` | Validate fuzzy mappings and unmapped hotspots via Gemini text API |
| 10 | `result_writer.py` | Serialize final output to `result.json` |
| 11 | `main.py` | Entry point: CLI args, pipeline orchestration, colored OCR fallback logic |

### Node.js Modules

| # | Module | Responsibility |
|---|--------|----------------|
| 12 | Upload Controller | Accept PDF, validate file type, save to storage, create Job |
| 13 | Python Bridge | Spawn Python subprocess, forward stderr to logger, parse stdout JSON protocol |
| 14 | Job Manager | Maintain job lifecycle state in MongoDB |
| 15 | Result Controller | Read Result from MongoDB, serve to frontend |
| 16 | Static File Server | Serve diagram PNG (local dev only; Cloudinary in production) |
| 17 | Cleanup Service | Delete temp files after result is saved |

### Utility Modules (`ai-worker/utils/`)

| Module | Responsibility |
|--------|----------------|
| `logger.py` | Centralised pipeline logger — writes to `sys.stderr` so output appears in Cloud Run logs |
| `gemini_http.py` | Gemini REST POST with retry logic (429 and 503 both retried with backoff) |

---

## 6. Folder Structure

```
ExplodedView/
│
├── storage/                              # Local dev shared storage (not committed)
│   ├── uploads/                          # Uploaded PDFs, keyed by jobId
│   └── outputs/                          # Per-job processing outputs
│       └── <jobId>/
│           ├── assembly_<n>/
│           │   └── diagram.png           # Cropped diagram image
│           └── result.json               # Final structured output
│
├── documentation/
│   ├── system-design.md                  # This file
│   ├── pipeline-fixes-july2026.md        # Chronological bug log
│   ├── backend-guide.md
│   ├── frontend-implementation.md
│   ├── implementation-progress.md
│   └── usecase.md
│
├── backend/                              # Node.js + Express
│   ├── src/
│   │   ├── routes/
│   │   ├── controllers/
│   │   ├── services/
│   │   │   ├── python.bridge.js          # Spawn Python, parse stdout, forward stderr
│   │   │   └── cleanup.service.js
│   │   ├── models/
│   │   │   ├── Job.model.js
│   │   │   └── Result.model.js
│   │   └── app.js
│   ├── Dockerfile                        # Combined Node.js + Python container
│   └── package.json
│
├── ai-worker/                            # Python CV pipeline
│   ├── main.py                           # CLI entry point + orchestration
│   ├── config.py                         # Shared constants: DPI, thresholds, API keys
│   ├── modules/
│   │   ├── page_classifier.py
│   │   ├── image_preprocessor.py
│   │   ├── circle_detector.py
│   │   ├── callout_reader.py
│   │   ├── strategy_d_recovery.py
│   │   ├── strategy_e_recovery.py
│   │   ├── bom_extractor.py
│   │   ├── mapping_engine.py
│   │   ├── llm_resolver.py
│   │   └── result_writer.py
│   ├── utils/
│   │   ├── logger.py                     # stderr-based logger for Cloud Run visibility
│   │   └── gemini_http.py                # Gemini REST with retry (429 + 503)
│   ├── interfaces/
│   └── requirements.txt
│
└── frontend/                             # React (deployed on Vercel)
    ├── src/
    │   ├── components/
    │   ├── hooks/
    │   │   └── useJobPoller.js
    │   ├── pages/
    │   └── App.jsx
    └── package.json
```

---

## 7. Processing Pipeline

```
[User uploads PDF]
        │
        ▼
[Node.js: save to /tmp/.../uploads/<jobId>.pdf]
[MongoDB: Job created — status: "pending"]
        │
        ▼
[Node.js: spawn Python subprocess]
[MongoDB: Job status → "processing"]
        │
        ▼
┌──────────────────────────────────────────────────────────┐
│                    Python Pipeline                         │
│                                                           │
│  Stage 1: page_classifier                                 │
│    Detect diagram + BOM pages (multi-assembly support)    │
│                  │                                        │
│  Stage 2: PDF rendering (PyMuPDF, 300 DPI)               │
│    → diagram.png (full page)                              │
│                  │                                        │
│  Stage 2b: Drawing area crop                             │
│    Horizontal projection profile → remove title/footer   │
│    → cropped diagram.png (~2481×2504px typical)          │
│                  │                                        │
│  Stage 3: image_preprocessor                             │
│    grayscale → blur → CLAHE → threshold → morph          │
│    → preprocessed.png (binary)                           │
│                  │                                        │
│  Stage 4: circle_detector                                │
│    Pass 1: detect_circles (binary — dark-outlined)       │
│    Pass 2: detect_colored_circles (HSV — filled/colored) │
│    merge_circle_lists → deduped circle list              │
│                  │                                        │
│  Stage 5: callout_reader                                 │
│    Strategy A: PyMuPDF text layer (instant, exact)       │
│    Strategy B: PaddleOCR tile scan (Pass 1 + Pass 2)     │
│    Strategy C: per-circle targeted OCR                   │
│    → raw OCR callouts                                    │
│    → colored-circle OCR callouts saved as fallbacks      │
│    → colored-circle OCR callouts dropped from callouts   │
│                  │                                        │
│  Stage 6: bom_extractor                                  │
│    pdfplumber (A) / PaddleOCR (B)                        │
│    → BOM rows [{ref_no, part_no, description, qty}]      │
│                  │                                        │
│  Stage D: strategy_d_recovery                            │
│    Per-circle PaddleOCR with multi-variant voting        │
│    Recovers refs OCR tile scan missed                    │
│                  │                                        │
│  Stage E: strategy_e_recovery (LLM_ENABLED only)        │
│    Gemini Vision multimodal — reads colored circle nums  │
│    Image resized to max 1500px before encoding           │
│    → recovered colored-circle callouts                   │
│                  │                                        │
│  Colored OCR fallback restoration                        │
│    For any ref not resolved by D or E:                   │
│    if ref in BOM and not already in callouts → restore   │
│                  │                                        │
│  Stage 7: mapping_engine                                 │
│    normalize → exact match → fuzzy match (edit dist ≤1) │
│    → mappings, unmapped_hotspots, unpositioned_bom_rows  │
│                  │                                        │
│  Stage 8: llm_resolver (LLM_ENABLED only)               │
│    Filter: skip unmapped refs not in BOM (false positives│
│    Gemini text API — validates fuzzy mappings            │
│    → llm_validations                                     │
│                  │                                        │
│  Stage 9: result_writer                                  │
│    → result.json                                         │
└──────────────────────────────────────────────────────────┘
        │
        ▼
[Node.js: reads result.json]
[Node.js: uploads diagram PNG to Cloudinary]
[MongoDB: Result saved, Job status → "done"]
[Node.js: cleanup.service deletes temp files]
        │
        ▼
[Frontend polls /api/jobs/:jobId → status: done]
[Frontend fetches /api/results/:jobId]
[React: renders Cloudinary diagram + SVG hotspot overlays + BOM table]
```

---

## 8. Node.js ↔ Python Communication

**Mechanism:** `child_process.spawn` (CLI subprocess)

```
Node.js spawns:
  python main.py --job-id abc123 --storage-path /tmp/explodedview-storage

Python reads:
  /tmp/explodedview-storage/uploads/abc123.pdf

Python writes:
  /tmp/explodedview-storage/outputs/abc123/assembly_0/diagram.png
  /tmp/explodedview-storage/outputs/abc123/result.json

Python signals via stdout (newline-delimited JSON):
  {"status": "processing", "step": "PAGE_CLASSIFICATION"}
  {"status": "processing", "step": "CIRCLE_DETECTION"}
  {"status": "done"}
  {"status": "error", "message": "No BOM table found on any page"}

Python diagnostic logs via stderr:
  2026-07-21 05:30:02 [INFO] pipeline.strategy_e — Strategy E: 9 missing ref(s)...

Node.js behaviour:
  - Each stdout JSON line → emit step update to client
  - Each stderr line → logger.warn() → visible in Cloud Run logs as [warn]
  - On "done" → read result.json → upload to Cloudinary → save Result → update Job
  - On "error" → update Job status to "error" + store errorMessage
  - On process exit code 1 with no stdout → treat as unknown error
```

**Critical:** Python logger must write to `sys.stderr`, not `sys.stdout`. stdout is the JSON protocol channel — any non-JSON line on stdout breaks the protocol. stderr is forwarded by Node.js as `logger.warn()` and always visible in Cloud Run.

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

TTL index: `createdAt` expires after **7 days**.

---

### Results Collection

```json
{
  "_id": "ObjectId",
  "jobId": "string",
  "processingDurationMs": "number",
  "totalPdfPages": "number",
  "assemblies": [
    {
      "assemblyIndex": "number",
      "pageMap": {
        "diagramPageIndex": "number",
        "bomPageIndex": "number"
      },
      "diagramImageUrl": "string (Cloudinary URL)",
      "imageWidth": "number (pixels)",
      "imageHeight": "number (pixels)",
      "totalParts": "number",
      "hotspots": [
        {
          "number": "string",
          "x": "number",
          "y": "number",
          "radius": "number",
          "extraction_method": "pymupdf | paddleocr | paddleocr_enhanced | gemini_vision",
          "score": "number (0.0–1.0)"
        }
      ],
      "bom": [
        {
          "ref_no": "string",
          "part_no": "string",
          "description": "string",
          "qty": "string"
        }
      ],
      "mappings": [
        {
          "hotspot_number": "string",
          "x": "number",
          "y": "number",
          "radius": "number",
          "bom": [{ "ref_no": "string", "part_no": "string", "description": "string", "qty": "string" }],
          "confidence": "number (0.0–1.0)"
        }
      ],
      "unmapped_hotspots": [{ "number": "string", "x": "number", "y": "number", "radius": "number" }],
      "unpositioned_bom_rows": [{ "ref_no": "string", "part_no": "string", "description": "string" }],
      "not_shown_bom_rows": [{ "ref_no": "string", "description": "string" }],
      "llm_validations": ["array of LLM validation decisions"]
    }
  ],
  "createdAt": "Date"
}
```

**Key fields:**
- `extraction_method` — tracks which strategy produced each hotspot (`gemini_vision` = Strategy E)
- `not_shown_bom_rows` — BOM rows explicitly marked "NOT SHOWN" on the diagram
- `llm_validations` — Gemini text API decisions on fuzzy/unmapped hotspots
- `diagramImageUrl` — Cloudinary CDN URL (replaces local `diagramImagePath`)

---

## 10. API Endpoints

| Method | Endpoint | Description | Response |
|--------|----------|-------------|----------|
| `POST` | `/api/upload` | Upload PDF, validate, create job, trigger pipeline | `{ jobId, status }` |
| `GET` | `/api/jobs/:jobId` | Poll job status and current step | `{ jobId, status, currentStep, errorMessage }` |
| `GET` | `/api/results/:jobId` | Fetch full result document | Full Result document |
| `GET` | `/static/outputs/:jobId/diagram.png` | Serve diagram PNG (local dev only) | `image/png` |
| `GET` | `/health` | Cloud Run health check | `{ status: "ok" }` |

---

## 11. File Lifecycle Management

### On Cloud Run (production)

Storage is ephemeral (`/tmp/explodedview-storage/`). Files exist only for the duration of pipeline processing:

```
UPLOAD:   /tmp/.../uploads/<jobId>.pdf          ← written by Node.js
PROCESS:  /tmp/.../outputs/<jobId>/assembly_0/diagram.png  ← written by Python
RESULT:   /tmp/.../outputs/<jobId>/result.json   ← written by Python
UPLOAD:   diagram.png → Cloudinary              ← Node.js after pipeline
SAVE:     result.json → MongoDB                 ← Node.js after pipeline
DELETE:   all /tmp/.../uploads/ and outputs/    ← cleanup.service.js
```

After the result is saved to MongoDB and the diagram is on Cloudinary, all local temp files are deleted. The frontend fetches the Cloudinary URL for the diagram image.

### In local development

Same flow, but `storage/` is a committed-excluded directory at the project root. `diagram.png` is served locally via `/static/outputs/:jobId/diagram.png`.

---

## 12. Architecture Decision Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Circle detection | `findContours` + circularity ratio for dark circles; HSV connected-components for colored | HoughCircles unstable on vector PDFs; two-pass approach handles both white-paper and colored-fill callouts without modifying the preprocessor |
| Primary text extraction | PyMuPDF direct (vector PDFs) | Zero OCR error when text is embedded; OCR only invoked when necessary |
| OCR engine | PaddleOCR | Superior accuracy on small isolated numeric text vs Tesseract; no PSM flag configuration required |
| Colored circle recovery | Gemini Vision (Strategy E) | PaddleOCR cannot reliably read numbers on colored/low-contrast backgrounds; Gemini Vision reads the number from the image directly using provided circle coordinates |
| LLM geometry role | None — LLM never generates coordinates | Hotspot coordinates must be pixel-accurate; Gemini identifies which candidate circle contains which number, but always uses coordinates from the CV detector |
| Strategy E image size | Resize to max 1500px before encoding | 2481×2504px PNG is ~5–8MB; too slow from Singapore to Gemini US endpoints; 1500px retains sufficient legibility for digit reading |
| Python logging | `sys.stderr` | stdout is the JSON protocol channel between Node.js and Python; stderr is forwarded by Node.js as `logger.warn()` and always visible in Cloud Run |
| Image hosting | Cloudinary | Cloud Run ephemeral storage cannot reliably serve files across requests or instances; Cloudinary provides CDN-hosted persistent URLs |
| Node↔Python bridge | CLI subprocess | Avoids second HTTP server; sufficient concurrency (Cloud Run concurrency=1); fully isolated per job |
| Deployment | Google Cloud Run | Serverless, scales to zero, supports custom Docker image with both Node.js and Python runtimes in one container |
| Fallback accuracy | Unpositioned > wrong position | A missing hotspot is an honest gap; a wrong hotspot misleads the user about part location. All fallback and recovery stages follow this principle |
| False positive filtering | Filter non-BOM refs before llm_resolver | OCR misreads (e.g. "28" from watermark text) cannot map to any BOM row; sending them to Gemini wastes quota and risks 429 rate limits |
| Colored OCR fallback | Save dropped OCR callouts; restore only if unresolved and in BOM | Provides resilience when Gemini fails (429/timeout) without blindly trusting low-quality colored-circle OCR readings |
