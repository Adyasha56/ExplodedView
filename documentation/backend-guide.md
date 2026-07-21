# Backend Guide — What's Built, How It Flows, How to Test It

**Status:** Milestone 1 complete (scaffolding). Controllers are stubs — Milestone 2 implements them.
**Last updated:** 2026-07-14

---

## Table of Contents

1. [What Has Been Built](#1-what-has-been-built)
2. [File-by-File Explanation](#2-file-by-file-explanation)
3. [Data Flow — Request Lifecycle](#3-data-flow--request-lifecycle)
4. [API Endpoints Reference](#4-api-endpoints-reference)
5. [Environment Setup](#5-environment-setup)
6. [How to Run the Backend](#6-how-to-run-the-backend)
7. [Testing Every Endpoint](#7-testing-every-endpoint)
8. [Cloudinary Integration Plan](#8-cloudinary-integration-plan)
9. [Gemini 2.5 Flash Integration Plan](#9-gemini-25-flash-integration-plan)
10. [What Is Still a Stub](#10-what-is-still-a-stub)

---

## 1. What Has Been Built

### Backend (Node.js)

| File | Status | Purpose |
|------|--------|---------|
| `src/app.js` | **Working** | Express server entry point — starts server, connects MongoDB |
| `src/config.js` | **Working** | Centralised config — reads all env vars, resolves paths |
| `src/utils/logger.js` | **Working** | Winston logger used by all files |
| `src/models/Job.model.js` | **Working** | MongoDB schema for a processing job |
| `src/models/Result.model.js` | **Working** | MongoDB schema for pipeline output |
| `src/routes/upload.routes.js` | **Working** | Registers `POST /api/upload` route |
| `src/routes/jobs.routes.js` | **Working** | Registers `GET /api/jobs/:jobId` and `GET /api/jobs/results/:jobId` |
| `src/controllers/upload.controller.js` | **Stub** | Returns 501 — implemented in Milestone 2 |
| `src/controllers/jobs.controller.js` | **Stub** | Returns 501 — implemented in Milestone 2 |
| `src/services/python.bridge.js` | **Stub** | Returns error — implemented in Milestone 2 |
| `src/services/cleanup.service.js` | **Stub** | No-op — implemented in Milestone 2 |

### Python Worker (ai-worker)

| File | Status | Purpose |
|------|--------|---------|
| `config.py` | **Working** | All pipeline constants and tunable parameters |
| `utils/logger.py` | **Working** | Centralised Python logger |
| `interfaces/ocr_engine.py` | **Working** | Protocol contract — OCR engine is swappable |
| `interfaces/pdf_extractor.py` | **Working** | Protocol contract — PDF extractor is swappable |
| `interfaces/mapping_strategy.py` | **Working** | Protocol contract — mapping algorithm is swappable |
| `modules/page_classifier.py` | **Stub** | Raises NotImplementedError |
| `modules/image_preprocessor.py` | **Stub** | Raises NotImplementedError |
| `modules/circle_detector.py` | **Stub** | Raises NotImplementedError |
| `modules/callout_reader.py` | **Stub** | Raises NotImplementedError |
| `modules/bom_extractor.py` | **Stub** | Raises NotImplementedError |
| `modules/mapping_engine.py` | **Stub** | Raises NotImplementedError |
| `modules/result_writer.py` | **Stub** | Raises NotImplementedError |
| `main.py` | **Working skeleton** | CLI entry, orchestrates all modules, emits JSON status lines |

### Shared Storage

```
storage/
├── uploads/    ← PDFs are saved here by Node.js (keyed by jobId)
└── outputs/    ← Python writes diagram.png + result.json here per job
```

---

## 2. File-by-File Explanation

---

### `backend/src/app.js` — The Entry Point

This is the first file Node.js runs. It:
1. Loads environment variables from `.env` via `dotenv`
2. Creates the Express app
3. Registers global middleware: CORS, JSON body parser
4. Mounts a **static file server** at `/static/outputs` → `storage/outputs/`
   - This is how the frontend will load `diagram.png` without a dedicated endpoint
5. Mounts all API routes
6. Registers a `/health` endpoint (useful to verify the server is alive)
7. Registers a 404 handler and a global error handler
8. Connects to MongoDB, then starts listening on `PORT`

**Depends on:** `config.js`, `logger.js`, `upload.routes.js`, `jobs.routes.js`

---

### `backend/src/config.js` — Single Source of Truth for Configuration

Every configurable value in the backend comes from here. No file should call `process.env` directly — they import from `config.js`.

```
config.server.port           → PORT env var (default 5000)
config.server.nodeEnv        → NODE_ENV env var
config.db.uri                → MONGO_URI env var
config.storage.root          → Resolved absolute path to /storage
config.storage.uploads       → storage/uploads/
config.storage.outputs       → storage/outputs/
config.python.executable     → 'python' or path to venv interpreter
config.python.workerPath     → Absolute path to ai-worker/main.py
config.jobs.ttlDays          → How long before jobs auto-expire (default 7 days)
config.upload.maxSizeBytes   → Max PDF size in bytes
config.upload.allowedMimeTypes → ['application/pdf']
```

**Why this matters:** If you change `STORAGE_PATH` in `.env`, every file that reads storage paths updates automatically — nothing is hardcoded anywhere else.

---

### `backend/src/utils/logger.js` — Winston Logger

All backend files import this instead of using `console.log`. It:
- In development: prints colorised output to console
- Format: `HH:mm:ss [level] message`
- Automatically prints stack traces for Error objects

Usage in any file:
```js
const logger = require('../utils/logger');
logger.info('Server started');
logger.error('Something failed', err);
logger.warn('This is a stub');
logger.debug('Detailed info');
```

---

### `backend/src/models/Job.model.js` — Job MongoDB Schema

A **Job** tracks the lifecycle of one PDF processing request.

```
jobId         → UUID string, unique, indexed (used in all API calls)
filename      → Original uploaded filename (e.g. "assembly.pdf")
status        → "pending" | "processing" | "done" | "error"
currentStep   → Which pipeline step is running (e.g. "circle_detection")
errorMessage  → Populated only when status = "error"
createdAt     → Auto-set by Mongoose timestamps
updatedAt     → Auto-updated by Mongoose on every save
```

**TTL Index:** MongoDB automatically deletes Job documents after `JOB_TTL_DAYS` days. This prevents the database from growing indefinitely.

**Relationship:** Every Result document has the same `jobId`. When a Job expires, the corresponding `storage/outputs/<jobId>/` directory is cleaned up by `cleanup.service.js`.

---

### `backend/src/models/Result.model.js` — Result MongoDB Schema

A **Result** holds the complete pipeline output for a job. Created only when the Python worker finishes successfully.

Key fields explained:

```
jobId               → Links back to Job (same UUID)
diagramImagePath    → Relative path used to serve diagram.png
imageWidth          → Pixel width of diagram.png — frontend NEEDS this
imageHeight         → Pixel height of diagram.png — frontend NEEDS this
processingDurationMs → How long the pipeline took (observability)
pageMap             → Which page was the diagram, which was the BOM
hotspots[]          → All detected circles with extracted numbers
bom[]               → All extracted BOM rows
mappings[]          → Successfully matched hotspot ↔ BOM pairs
unmappedHotspots[]  → Hotspots that had no BOM match
unmappedBomRows[]   → BOM rows that no hotspot claimed
confidence          → Per-mapping score: 1.0 = exact, 0.7 = fuzzy
```

**Why `imageWidth` / `imageHeight`?** The frontend overlays SVG circles on top of the diagram image. If the image is scaled down to fit the screen, the pixel coordinates in `hotspots[]` must be scaled proportionally. Without knowing the original dimensions, the overlays will be mispositioned.

---

### `backend/src/routes/upload.routes.js` — Upload Route Registration

Registers one route: `POST /api/upload` → `upload.controller.handleUpload`

This file's only job is to map the URL to the controller. No logic here.

---

### `backend/src/routes/jobs.routes.js` — Jobs Route Registration

Registers two routes:
- `GET /api/jobs/:jobId` → `jobs.controller.getJobStatus`
- `GET /api/jobs/results/:jobId` → `jobs.controller.getResult`

---

### `backend/src/controllers/upload.controller.js` — Upload Handler (Stub)

**Currently returns 501 Not Implemented.**

When implemented in Milestone 2, this will:
1. Receive the PDF via `multer` middleware
2. Validate: file must be `.pdf`, size must be within limit
3. Generate a UUID as `jobId`
4. Save file to `storage/uploads/<jobId>.pdf`
5. Create a `Job` document in MongoDB with `status: "pending"`
6. Call `python.bridge.runPipeline(jobId)` — starts the Python worker asynchronously
7. Return `{ jobId, status: "pending" }` to the client immediately

The pipeline runs in the background — the client polls for status.

---

### `backend/src/controllers/jobs.controller.js` — Job Status + Result Handler (Stub)

**Currently returns 501 Not Implemented.**

When implemented in Milestone 2:

`getJobStatus`: Reads the `Job` document by `jobId` and returns `{ jobId, status, currentStep, errorMessage }`.

`getResult`: Reads the `Result` document by `jobId` and returns the full result JSON. Returns 404 if job is not done yet.

---

### `backend/src/services/python.bridge.js` — Node ↔ Python Bridge (Stub)

**Currently throws "Not implemented".**

When implemented in Milestone 2, `runPipeline(jobId)` will:
1. Spawn: `python main.py --job-id <jobId> --storage-path <STORAGE_PATH>`
2. Listen to the Python process's stdout line by line
3. Each line is a JSON status object:
   - `{"status": "processing", "step": "circle_detection"}` → update `Job.currentStep` in MongoDB
   - `{"status": "done"}` → read `result.json` → save `Result` doc → update `Job.status = "done"`
   - `{"status": "error", "message": "..."}` → update `Job.status = "error"`
4. On process exit with code 1 and no prior signal → treat as unknown error

---

### `backend/src/services/cleanup.service.js` — File Lifecycle (Stub)

**Currently a no-op.**

When implemented:

`cleanupJobFiles(jobId)`: After a job reaches "done", deletes:
- `storage/uploads/<jobId>.pdf` (raw PDF, no longer needed)
- `storage/outputs/<jobId>/preprocessed.png` (debug image)

Keeps `diagram.png` and `result.json` so the frontend can still access them.

---

## 3. Data Flow — Request Lifecycle

### Upload Flow

```
Client
  │
  │  POST /api/upload  (multipart/form-data, file=assembly.pdf)
  ▼
app.js
  │ routes the request to →
  ▼
upload.routes.js
  │ calls →
  ▼
upload.controller.js
  │ 1. multer saves temp file
  │ 2. validates PDF
  │ 3. moves to storage/uploads/<jobId>.pdf
  │ 4. creates Job { jobId, status: "pending" } in MongoDB
  │ 5. calls python.bridge.runPipeline(jobId)  [async, does NOT await]
  │ 6. immediately responds →
  ▼
Client  ←  { jobId: "abc-123", status: "pending" }
```

### Python Pipeline (Background)

```
python.bridge.js
  │
  │  spawns child process:
  │  python main.py --job-id abc-123 --storage-path /app/storage
  ▼
ai-worker/main.py
  │ reads  → storage/uploads/abc-123.pdf
  │ writes → storage/outputs/abc-123/diagram.png
  │ writes → storage/outputs/abc-123/result.json
  │ emits to stdout →
  │   {"status":"processing","step":"page_classification"}
  │   {"status":"processing","step":"circle_detection"}
  │   ...
  │   {"status":"done"}
  ▼
python.bridge.js (listening to stdout)
  │ on each line → updates Job.currentStep in MongoDB
  │ on "done"    → reads result.json
  │              → saves Result document to MongoDB
  │              → updates Job.status = "done"
  │              → calls cleanup.service.cleanupJobFiles(jobId)
```

### Poll Flow (Frontend polling for status)

```
Client
  │  GET /api/jobs/abc-123
  ▼
jobs.routes.js → jobs.controller.getJobStatus
  │  reads Job from MongoDB
  ▼
Client ← { jobId, status: "processing", currentStep: "circle_detection" }

... client keeps polling until status = "done" ...

Client
  │  GET /api/jobs/results/abc-123
  ▼
jobs.routes.js → jobs.controller.getResult
  │  reads Result from MongoDB
  ▼
Client ← full Result JSON (mappings, hotspots, BOM, imageWidth, imageHeight, ...)
```

### Diagram Image Flow

```
Client
  │  GET /static/outputs/abc-123/diagram.png
  ▼
app.js (express.static middleware)
  │  serves file directly from storage/outputs/abc-123/diagram.png
  ▼
Client ← PNG image (no controller involved, served as static asset)
```

---

## 4. API Endpoints Reference

| Method | URL | Request | Response | Status |
|--------|-----|---------|----------|--------|
| `GET` | `/health` | — | `{ status: "ok", env: "development" }` | **Live** |
| `POST` | `/api/upload` | `multipart/form-data` with `file` | `{ jobId, status }` | **Stub (501)** |
| `GET` | `/api/jobs/:jobId` | — | `{ jobId, status, currentStep, errorMessage }` | **Stub (501)** |
| `GET` | `/api/jobs/results/:jobId` | — | Full Result document | **Stub (501)** |
| `GET` | `/static/outputs/:jobId/diagram.png` | — | PNG image | **Live** |

---

## 5. Environment Setup

```bash
# 1. Copy the example env file
cp backend/.env.example backend/.env

# 2. Edit backend/.env with your values:
PORT=5000
NODE_ENV=development
MONGO_URI=mongodb://localhost:27017/exploded_view
STORAGE_PATH=../../storage        # relative to backend/src/config.js
PYTHON_EXECUTABLE=python
PYTHON_WORKER_PATH=../../ai-worker/main.py
JOB_TTL_DAYS=7
MAX_UPLOAD_SIZE_MB=50
```

---

## 6. How to Run the Backend

```bash
cd backend

# Install dependencies (first time only)
npm install

# Run in development mode (auto-restarts on file change)
npm run dev

# Expected output:
# HH:mm:ss [info] MongoDB connected: mongodb://localhost:27017/exploded_view
# HH:mm:ss [info] Server running on port 5000 [development]
# HH:mm:ss [info] Storage root: D:\ExplodedView\storage
```

**Prerequisites:**
- Node.js >= 18
- MongoDB running locally on port 27017 (or update `MONGO_URI`)

---

## 7. Testing Every Endpoint

### Tool: Postman or curl

---

#### Test 1 — Health Check (should work right now)

```
GET http://localhost:5000/health
```

Expected response:
```json
{ "status": "ok", "env": "development" }
```

---

#### Test 2 — Upload PDF (currently returns 501 — implemented in Milestone 2)

```
POST http://localhost:5000/api/upload
Content-Type: multipart/form-data
Body: file = <your PDF>
```

Expected response (after Milestone 2):
```json
{ "jobId": "550e8400-e29b-41d4-a716-446655440000", "status": "pending" }
```

---

#### Test 3 — Poll Job Status (currently returns 501 — implemented in Milestone 2)

```
GET http://localhost:5000/api/jobs/550e8400-e29b-41d4-a716-446655440000
```

Expected response:
```json
{
  "jobId": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "currentStep": "circle_detection",
  "errorMessage": null
}
```

---

#### Test 4 — Fetch Result (currently returns 501 — implemented in Milestone 2)

```
GET http://localhost:5000/api/jobs/results/550e8400-e29b-41d4-a716-446655440000
```

Expected response (after pipeline completes):
```json
{
  "jobId": "...",
  "imageWidth": 2480,
  "imageHeight": 3508,
  "processingDurationMs": 4200,
  "mappings": [...],
  "unmappedHotspots": [...],
  "unmappedBomRows": [...]
}
```

---

#### Test 5 — Serve Diagram Image (works after pipeline writes the file)

```
GET http://localhost:5000/static/outputs/<jobId>/diagram.png
```

Opens the extracted diagram PNG directly in the browser.

---

## 8. Cloudinary Integration Plan

**Decision:** Use Cloudinary for production file storage. Keep local `storage/` for development.

**How this fits the current architecture:**

The upload controller currently saves the PDF to `storage/uploads/<jobId>.pdf`. To add Cloudinary:

1. Add `cloudinary` npm package and `CLOUDINARY_URL` env var
2. After `multer` saves the file locally (temp), upload to Cloudinary
3. Store the returned Cloudinary URL in the `Job` document (`pdfUrl` field)
4. For local dev, skip Cloudinary and use the local path

The Python worker always reads from the local `storage/` path — so Node.js must download the PDF from Cloudinary to local storage before spawning Python, or the Python worker adds direct Cloudinary download support.

**Recommended approach for MVP:** Upload to Cloudinary, but before spawning Python, download the file to `storage/uploads/<jobId>.pdf`. Python worker stays unchanged.

**Env vars to add:**
```
CLOUDINARY_CLOUD_NAME=your_cloud
CLOUDINARY_API_KEY=your_key
CLOUDINARY_API_SECRET=your_secret
USE_CLOUDINARY=false   # set to true in production
```

---

## 9. Gemini 2.5 Flash Integration Plan

**Yes — Gemini 2.5 Flash is an excellent fit for this project.**

It has multimodal vision capabilities (text + image input), which aligns with our LLM layer role.

**Where Gemini fits in the pipeline (per architecture philosophy):**

| Use Case | When triggered | What Gemini does |
|----------|---------------|-----------------|
| **Ambiguous mapping resolution** | When `mapping_engine` has unmatched hotspots after fuzzy match | Given the diagram image + BOM table, Gemini reasons about which hotspot number maps to which BOM entry |
| **OCR correction** | When PaddleOCR returns a non-numeric or low-confidence result from a callout crop | Gemini is given the circle crop image and asked "what number is shown here?" |
| **Page classification assist** | When `page_classifier` returns `confidence: "low"` | Gemini is given page thumbnails and asked to identify diagram vs BOM |
| **BOM extraction fallback** | When neither pdfplumber nor PaddleOCR produces a clean table | Gemini is given the BOM page image and asked to extract the table as JSON |

**What Gemini does NOT do:**
- Gemini never produces hotspot pixel coordinates (CV handles geometry)
- Gemini never replaces `circle_detector.py`

**Integration plan:**
1. Add `google-generativeai` Python package to `requirements.txt`
2. Add `GEMINI_API_KEY` to `ai-worker/.env.example`
3. Add `interfaces/llm_provider.py` — Protocol for swappable LLM (so Gemini can be swapped for GPT-4 Vision later)
4. Create `modules/llm_resolver.py` — called by `mapping_engine` and `callout_reader` when deterministic methods are insufficient

---

## 10. What Is Still a Stub

The following files return **501 Not Implemented** or **NotImplementedError**:

| File | Implemented in |
|------|---------------|
| `upload.controller.js` | Milestone 2 |
| `jobs.controller.js` | Milestone 2 |
| `python.bridge.js` | Milestone 2 |
| `cleanup.service.js` | Milestone 2 |
| All `ai-worker/modules/*.py` | Milestone 2 (Python pipeline) |

The `/health` endpoint and static file serving are **live** and testable right now.
The models are **defined** and will work as soon as MongoDB is connected and controllers are implemented.
