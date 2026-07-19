# ExplodedView

ExplodedView is a web application that analyzes engineering PDF documents containing exploded-view assembly diagrams and Bill of Materials tables. It automatically detects part callout numbers on the diagram, extracts the BOM, maps each callout to its corresponding part, and presents the result as an interactive viewer where clicking a hotspot highlights the associated BOM row and vice versa.

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [System Architecture](#system-architecture)
3. [Repository Structure](#repository-structure)
4. [Data Flow](#data-flow)
5. [AI Pipeline — Stage by Stage](#ai-pipeline--stage-by-stage)
6. [Libraries and Technologies](#libraries-and-technologies)
7. [API Reference](#api-reference)
8. [Frontend Architecture](#frontend-architecture)
9. [Deployment](#deployment)
10. [Deployment Issues Encountered](#deployment-issues-encountered)
11. [Environment Variables](#environment-variables)
12. [Local Development](#local-development)

---

## Problem Statement

Engineering PDFs for mechanical assemblies typically contain two types of pages: an exploded-view diagram and a Bill of Materials. The diagram shows numbered callout circles (hotspots) positioned over individual parts. The BOM is a table that maps each reference number to a part number, description, and quantity.

Reading these documents manually is slow. A technician must visually scan the diagram to find a callout number, then search the BOM table to find the matching row. For assemblies with 50 or more parts, this process is error-prone and time-consuming.

The problem ExplodedView solves is fully automated: given any engineering PDF, locate every callout circle on the diagram, extract every row from the BOM, join them, and produce an interactive digital interface where a technician can click any part on the diagram to instantly see its specification.

The challenge is that these PDFs come in many formats. Some are vector PDFs where text is stored as selectable characters. Others are scans where the entire page is a raster image. The callout numbers may be printed inside circles, attached to leader lines, or embedded in text layers that do not align with visual positions. No single extraction technique works for all documents, so the pipeline uses multiple strategies in priority order and falls back gracefully.

---

## System Architecture

```
+------------------+          HTTPS           +---------------------------+
|                  | -----------------------> |                           |
|  Vercel          |                          |  Google Cloud Run         |
|  (React + Vite)  |                          |                           |
|                  | <----------------------- |  +---------------------+  |
+------------------+      JSON responses      |  |  Node.js / Express  |  |
                                              |  |  (API layer)        |  |
                                              |  +----------+----------+  |
                                              |             |              |
                                              |             | spawn        |
                                              |             v              |
                                              |  +---------------------+  |
                                              |  |  Python AI Worker   |  |
                                              |  |                     |  |
                                              |  |  - PyMuPDF          |  |
                                              |  |  - pdfplumber       |  |
                                              |  |  - OpenCV           |  |
                                              |  |  - PaddleOCR        |  |
                                              |  |  - Levenshtein      |  |
                                              |  |  - Gemini (REST)    |  |
                                              |  +---------------------+  |
                                              |                           |
                                              +---------------------------+
                                                          |
                              +---------------------------+---------------------------+
                              |                                                       |
                              v                                                       v
                   +--------------------+                               +------------------+
                   |  MongoDB Atlas     |                               |  Cloudinary CDN  |
                   |  (jobs + results)  |                               |  (diagram images)|
                   +--------------------+                               +------------------+
```

![System Architecture and Workflow](images/Exploded%20View%20-%20visual%20selection%20(1).png)

The frontend is a static React application served from Vercel. It communicates with a single backend service running on Google Cloud Run. The backend container holds both the Node.js API server and the Python AI worker. When a PDF is uploaded, Node.js spawns Python as a child process, waits for it to complete, uploads the resulting diagram image to Cloudinary, stores the structured result in MongoDB, and returns the outcome to the waiting HTTP client. The frontend then fetches the result and renders the interactive viewer.

---

## Repository Structure

```
ExplodedView/
|
+-- backend/                        Node.js / Express API
|   +-- src/
|   |   +-- app.js                  Express setup, middleware, server startup
|   |   +-- config.js               Centralised config from environment variables
|   |   +-- constants/
|   |   |   +-- pipeline.js         Pipeline step name constants
|   |   +-- controllers/
|   |   |   +-- upload.controller.js  POST /api/upload handler
|   |   +-- middleware/
|   |   |   +-- upload.middleware.js  Multer file validation and storage
|   |   +-- models/
|   |   |   +-- Job.model.js        MongoDB job document schema
|   |   |   +-- Result.model.js     MongoDB result document schema
|   |   +-- routes/
|   |   |   +-- upload.routes.js
|   |   |   +-- jobs.routes.js
|   |   |   +-- results.routes.js
|   |   +-- services/
|   |   |   +-- python.bridge.js    Spawns Python, handles stdout/stderr protocol
|   |   |   +-- cloudinary.service.js  Uploads diagram images to Cloudinary
|   |   |   +-- cleanup.service.js  Deletes temporary files after job completes
|   |   +-- utils/
|   |       +-- logger.js           Winston logger
|   +-- Dockerfile                  Combined Node + Python container
|   +-- package.json
|
+-- ai-worker/                      Python AI pipeline
|   +-- main.py                     Pipeline entry point, CLI argument parsing
|   +-- config.py                   All tunable constants and path resolution
|   +-- constants/
|   |   +-- pipeline_state.py       Step name strings emitted to stdout
|   +-- interfaces/                 Abstract base classes
|   +-- modules/
|   |   +-- page_classifier.py      Identifies diagram-BOM page pairs
|   |   +-- image_preprocessor.py   CLAHE, deskew, morphological cleanup
|   |   +-- circle_detector.py      Contour-based callout circle detection
|   |   +-- callout_reader.py       Multi-strategy OCR for callout numbers
|   |   +-- bom_extractor.py        BOM table extraction (pdfplumber + PaddleOCR)
|   |   +-- mapping_engine.py       Exact and fuzzy hotspot-to-BOM join
|   |   +-- llm_resolver.py         Gemini REST API wrapper
|   |   +-- strategy_d_recovery.py  Per-circle OCR recovery for missed callouts
|   |   +-- strategy_e_recovery.py  Gemini Vision recovery for unresolved hotspots
|   |   +-- result_writer.py        Writes structured result.json
|   +-- utils/
|       +-- logger.py
|
+-- frontend/                       React 18 + Vite application
|   +-- src/
|   |   +-- api/
|   |   |   +-- pipeline.js         API client (uploadPdf, getJobStatus, getResult)
|   |   |   +-- static.js           URL helper for Cloudinary vs local static images
|   |   +-- hooks/
|   |   |   +-- useUpload.js        Upload state management
|   |   |   +-- useJobPoller.js     Polls job status after upload
|   |   +-- components/
|   |   |   +-- upload/             DropZone, UploadBar
|   |   |   +-- pipeline/           PipelineTracker progress display
|   |   |   +-- viewer/             DiagramCanvas, BomPanel, HotspotPin, AssemblySection
|   |   |   +-- workspace/          Workspace (top-level layout and state)
|   |   |   +-- shared/             ErrorBanner
|   |   +-- utils/
|   |       +-- pipelineSteps.js    Maps pipeline step names to display labels
|   +-- index.html
|   +-- vite.config.js
|
+-- render.yaml                     Render deployment config (legacy, kept for reference)
+-- storage/                        Local dev only — uploads and outputs
```

---

## Data Flow

```
USER                   FRONTEND                  BACKEND (Cloud Run)                 EXTERNAL
 |                        |                              |                               |
 | drop PDF               |                              |                               |
 |----------------------->|                              |                               |
 |                        | POST /api/upload             |                               |
 |                        | (multipart, PDF file)        |                               |
 |                        |----------------------------->|                               |
 |                        |                              |                               |
 |                        |    [HTTP request stays open] |                               |
 |                        |                              | create Job in MongoDB         |
 |                        |                              |------------------------------>|
 |                        |                              |                               |
 |                        |                              | spawn python main.py          |
 |                        |                              |-------+                       |
 |                        |                              |       |                       |
 |                        |                              |       | page_classification   |
 |                        |                              |       | pdf_rendering         |
 |                        |                              |       | image_preprocessing   |
 |                        |                              |       | circle_detection      |
 |                        |                              |       | callout_reading (OCR) |
 |                        |                              |       | bom_extraction        |
 |                        |                              |       | mapping               |
 |                        |                              |       | llm_validation        |
 |                        |                              |       | result_writing        |
 |                        |                              |<------+                       |
 |                        |                              |                               |
 |                        |                              | upload diagram.png            |
 |                        |                              |------------------------------>|
 |                        |                              |    Cloudinary returns URL     |
 |                        |                              |<------------------------------|
 |                        |                              |                               |
 |                        |                              | save Result to MongoDB        |
 |                        |                              | mark Job done                 |
 |                        |                              |------------------------------>|
 |                        |                              |                               |
 |                        | 200 { jobId, status:'done' } |                               |
 |                        |<-----------------------------|                               |
 |                        |                              |                               |
 |                        | GET /api/results/:jobId      |                               |
 |                        |----------------------------->|                               |
 |                        | result JSON                  |                               |
 |                        |<-----------------------------|                               |
 |                        |                              |                               |
 | interactive viewer     |                              |                               |
 |<-----------------------|                              |                               |
 |                        |                              |                               |
 | click hotspot          |                              |                               |
 |----------------------->|                              |                               |
 | BOM row highlights     |                              |                               |
 |<-----------------------|                              |                               |
```

The HTTP request for `POST /api/upload` remains open for the entire pipeline duration (typically 30 seconds to several minutes depending on PDF complexity and whether Gemini LLM recovery is triggered). This design was deliberately chosen for Google Cloud Run, where CPU is only guaranteed to a container during an active HTTP request. Keeping the request open guarantees CPU allocation throughout processing without requiring instance-based billing.

---

## AI Pipeline — Stage by Stage

![AI Worker Internal Pipeline Flow](images/Exploded-View%20-%20visual%20selection.png)

The pipeline is a sequential chain of nine stages. Each stage emits a JSON status line to stdout, which Node.js reads and writes to MongoDB so the frontend can display live progress.

```
PDF file on disk
      |
      v
+---------------------+
|  1. Page            |
|     Classification  |
|                     |
|  pdfplumber scans   |
|  every page for     |
|  table structure.   |
|  Pages with high    |
|  cell counts are    |
|  BOM candidates.    |
|  Adjacent non-table |
|  pages are diagram  |
|  candidates. Pairs  |
|  are formed.        |
|  Multi-assembly     |
|  PDFs produce       |
|  multiple pairs.    |
+---------------------+
      |
      v
+---------------------+
|  2. PDF Rendering   |
|                     |
|  PyMuPDF renders    |
|  the diagram page   |
|  to a PNG at 300    |
|  DPI. This image    |
|  is the primary     |
|  input for all      |
|  computer vision    |
|  stages.            |
+---------------------+
      |
      v
+---------------------+
|  3. Image           |
|     Preprocessing   |
|                     |
|  OpenCV pipeline:   |
|  - Grayscale        |
|  - CLAHE contrast   |
|    enhancement      |
|  - Morphological    |
|    close to join    |
|    broken lines     |
|  - Deskew if        |
|    rotation > 0.5   |
|    degrees          |
+---------------------+
      |
      v
+---------------------+
|  4. Circle          |
|     Detection       |
|                     |
|  OpenCV contour     |
|  analysis. Each     |
|  contour is scored  |
|  for circularity    |
|  (4*pi*area /       |
|  perimeter^2).      |
|  Circles above the  |
|  threshold and      |
|  within the radius  |
|  bounds are         |
|  accepted as        |
|  callout hotspots.  |
|  Centre (x,y) and   |
|  radius are stored  |
|  for each.          |
+---------------------+
      |
      v
+---------------------+
|  5. Callout         |
|     Reading         |
|                     |
|  Three strategies   |
|  in priority order: |
|                     |
|  A. PyMuPDF text    |
|     layer scan.     |
|     Fast, perfect   |
|     for vector PDFs.|
|                     |
|  B. PaddleOCR full  |
|     image scan.     |
|     Two passes:     |
|     broad tiles     |
|     then seed-      |
|     expansion crops |
|     around hits.    |
|                     |
|  C. Per-circle OCR. |
|     Individual crop |
|     around each     |
|     accepted circle.|
|     Recovers numbers|
|     missed in dense |
|     clusters.       |
|                     |
|  False-positive     |
|  filtering: if page |
|  has strong circle  |
|  evidence, OCR hits |
|  not near any circle|
|  are rejected.      |
+---------------------+
      |
      v
+---------------------+
|  6. BOM Extraction  |
|                     |
|  Two strategies:    |
|                     |
|  A. pdfplumber      |
|     table extract.  |
|     Reliable for    |
|     vector PDFs.    |
|                     |
|  B. PaddleOCR on    |
|     rendered BOM    |
|     page image.     |
|     Used for        |
|     scanned PDFs.   |
|                     |
|  Output: list of    |
|  {ref_no, part_no,  |
|  description, qty}  |
+---------------------+
      |
      v
+---------------------+
|  7. Mapping         |
|                     |
|  Three-stage join:  |
|                     |
|  1. Normalise both  |
|     sides (strip    |
|     leading zeros,  |
|     whitespace).    |
|                     |
|  2. Exact match.    |
|     Duplicate BOM   |
|     refs all attach |
|     to one hotspot. |
|                     |
|  3. Fuzzy match.    |
|     Levenshtein     |
|     distance <= 1.  |
|     Best unclaimed  |
|     row wins.       |
|                     |
|  Unmatched hotspots |
|  and unmatched BOM  |
|  rows are reported  |
|  separately.        |
+---------------------+
      |
      v
+---------------------+
|  8. LLM Validation  |
|     (Strategy E)    |
|                     |
|  Optional stage.    |
|  Fires when         |
|  LLM_ENABLED=true   |
|  and there are      |
|  unresolved         |
|  hotspots.          |
|                     |
|  Gemini Vision      |
|  receives the       |
|  diagram image and  |
|  a list of circle   |
|  positions. It      |
|  reads the numbers  |
|  directly from the  |
|  image and returns  |
|  callout-to-number  |
|  assignments for    |
|  circles that OCR   |
|  missed.            |
|                     |
|  Called via REST    |
|  (not SDK) to avoid |
|  a protobuf version |
|  conflict between   |
|  google-generativeai|
|  and paddlepaddle.  |
+---------------------+
      |
      v
+---------------------+
|  9. Result Writing  |
|                     |
|  result.json is     |
|  written to disk.   |
|  Contains: all      |
|  assemblies, each   |
|  with mappings,     |
|  unmapped hotspots, |
|  unpositioned BOM   |
|  rows, diagram      |
|  image path, page   |
|  map, image dims.   |
+---------------------+
      |
      v
   result.json
```

---

## Libraries and Technologies

### Backend — Node.js

| Library | Version | Why it is used |
|---|---|---|
| Express | 4.19 | HTTP server and routing framework. Chosen for its minimal surface area — the API has four routes and does not need a full framework. |
| Mongoose | 8.4 | MongoDB ODM. Provides schema validation, typed models, and connection management for the Job and Result documents. |
| Multer | 2.2 | Multipart form data parser for file uploads. Generates a unique job ID per upload and saves the PDF to the configured storage path. |
| Cloudinary SDK | 2.5 | Uploads the rendered diagram PNG to Cloudinary CDN after the pipeline completes, returning a persistent public URL for the frontend to load. |
| Winston | 3.13 | Structured logging. All log lines include a timestamp and level, making Cloud Run log filtering straightforward. |
| UUID | 11 | Generates the job ID (a v4 UUID) that links the uploaded file, the MongoDB Job document, the Python pipeline run, and the Result document. |
| dotenv | 16 | Loads environment variables from `.env` in development. In production (Cloud Run), variables are injected by the runtime and dotenv is a no-op. |
| cors | 2.8 | Enables cross-origin requests from the Vercel frontend domain to the Cloud Run backend. |

### AI Worker — Python

| Library | Version | Why it is used |
|---|---|---|
| PyMuPDF (fitz) | 1.24.5 | Primary PDF reader. Used for direct text layer extraction (Strategy A callout reading), page rendering to PNG at configurable DPI, and page count. Faster and more accurate than alternatives for vector PDFs. |
| pdfplumber | 0.11.1 | Structured table extraction. Used for page classification (detecting BOM pages by cell count) and BOM extraction from vector PDFs (Strategy A BOM). pdfplumber's table API returns rows and cells directly, removing the need to parse raw text coordinates. |
| OpenCV (headless) | 4.6.0.66 | Computer vision. Used for image preprocessing (CLAHE contrast enhancement, morphological operations, deskew), contour-based circle detection, and image cropping for per-circle OCR. The headless variant is used because the server has no display — it excludes GUI dependencies. Pinned to 4.6.0.66 because paddleocr 2.7.3 requires OpenCV below 4.8. |
| NumPy | 1.26.4 | Array operations required by OpenCV. All image data is represented as NumPy arrays. |
| PaddlePaddle | 2.6.2 | The runtime engine for PaddleOCR. CPU build. Provides the tensor computation backend. |
| PaddleOCR | 2.7.3 | Optical character recognition. Used for callout reading on scanned or image-based PDFs (Strategies B and C) and for BOM extraction when pdfplumber finds no table (Strategy B BOM). PaddleOCR was chosen over Tesseract because it is more accurate on small digit crops and handles rotated or low-contrast text better in the context of engineering diagrams. |
| Pillow | 10.3.0 | Image I/O used internally by PaddleOCR for loading and saving image files. |
| python-Levenshtein | 0.25.1 | Computes edit distance between callout numbers and BOM reference numbers during fuzzy matching. A distance of 1 handles common OCR misreads (0 vs O, 1 vs I) and trailing character noise. |
| python-dotenv | 1.0.1 | Loads the ai-worker `.env` file in local development. In production, all environment variables are passed from the Node.js process environment. |
| requests (transitive) | - | Used for the Gemini Vision REST API call. The Google Generative AI Python SDK was not used because it requires protobuf >= 5, which conflicts with paddlepaddle's requirement of protobuf <= 3.20.2. Calling Gemini via raw HTTP avoids this dependency conflict entirely. |

### Frontend — React

| Library | Version | Why it is used |
|---|---|---|
| React | 18.3 | UI component library. State management for the upload flow, pipeline progress display, and interactive diagram viewer is handled with built-in hooks (useState, useEffect, useRef). No external state manager was needed. |
| Vite | 5.4 | Build tool and dev server. Provides fast hot module replacement in development and an optimised production bundle. The dev server proxy forwards `/api` and `/static` requests to the local Node.js backend, so the frontend needs no environment configuration in development. |
| Tailwind CSS | 3.4 | Utility-first CSS framework. Used for all styling. Eliminates the need for separate CSS files and keeps component markup self-contained. |
| React Icons | 5.3 | SVG icon components. Used for step state icons in the pipeline tracker (check, cross, circle) and file/close icons in the upload bar. |

### Infrastructure

| Service | Why it is used |
|---|---|
| Google Cloud Run | Serverless container platform. Runs the Docker image containing both Node.js and Python. Scales to zero when idle (no cost), scales up on demand. The 2 GiB memory limit accommodates PaddleOCR's runtime memory requirement. Request timeout of 900 seconds covers the full pipeline duration for complex PDFs. |
| MongoDB Atlas | Managed MongoDB. Stores Job documents (status, pipeline step, error messages) and Result documents (full structured output including mappings, BOM rows, image paths). The Job document enables the frontend to display pipeline progress and the Result document enables the viewer. |
| Cloudinary | Cloud image storage and CDN. Receives the rendered diagram PNG after the pipeline completes. The frontend loads diagram images directly from Cloudinary's CDN, which is faster than serving them from the backend and does not require persistent storage on Cloud Run (which has an ephemeral filesystem). |
| Vercel | Static site hosting for the React frontend. Deploys automatically from the GitHub main branch. The `VITE_API_URL` environment variable is set in the Vercel dashboard to point to the Cloud Run backend URL. |
| Docker | The backend Dockerfile creates a single image with Node.js 20, Python 3.11, all system libraries (OpenCV, PaddlePaddle dependencies), all Python packages, and all Node.js packages. PaddleOCR models are downloaded and baked into the image at build time so they are available at runtime without any network download. |

---

## API Reference

### POST /api/upload

Accepts a multipart PDF upload. Runs the full AI pipeline synchronously and returns when complete.

The HTTP request remains open for the full pipeline duration. This is intentional: on Google Cloud Run, CPU is only guaranteed during an active request. Keeping the connection open ensures the Python subprocess has CPU throughout processing.

Request: `multipart/form-data` with field `file` containing the PDF.

Success response (HTTP 200):
```json
{
  "jobId": "550e8400-e29b-41d4-a716-446655440000",
  "status": "done"
}
```

Error response (HTTP 500):
```json
{
  "jobId": "550e8400-e29b-41d4-a716-446655440000",
  "status": "error",
  "error": "Python process exited with code 1. stderr tail: ..."
}
```

---

### GET /api/jobs/:jobId

Returns the current status of a job. Used by the frontend to check progress and by the polling hook after upload completes.

Response:
```json
{
  "jobId": "550e8400-e29b-41d4-a716-446655440000",
  "status": "done",
  "pipelineStep": "COMPLETED",
  "filename": "assembly.pdf",
  "fileSizeBytes": 2048000,
  "errorMessage": null
}
```

Status values: `pending`, `processing`, `done`, `error`.

---

### GET /api/results/:jobId

Returns the full structured result for a completed job.

Response structure:
```json
{
  "jobId": "...",
  "totalPdfPages": 4,
  "assemblies": [
    {
      "assemblyIndex": 0,
      "pageMap": {
        "diagramPageIndex": 0,
        "bomPageIndex": 1
      },
      "imageWidth": 2480,
      "imageHeight": 3508,
      "diagramImagePath": "https://res.cloudinary.com/...",
      "mappings": [
        {
          "hotspotNumber": "1",
          "cx": 412,
          "cy": 830,
          "radius": 24,
          "confidence": 1.0,
          "bom": [
            {
              "refNo": "1",
              "partNo": "HC-001-A",
              "description": "Cylinder Housing",
              "qty": "1"
            }
          ]
        }
      ],
      "unmappedHotspots": [],
      "unpositionedBomRows": []
    }
  ]
}
```

---

### GET /health

Returns the health status of the backend service.

Response:
```json
{
  "status": "ok",
  "env": "production",
  "storage": "/tmp/explodedview-storage"
}
```

---

## Frontend Architecture

The frontend has three display states managed by `Workspace.jsx`.

```
                    +------------------+
                    |   Upload State   |
                    |                  |
                    |  DropZone (no    |
                    |  file selected)  |
                    |                  |
                    |  UploadBar (file |
                    |  selected, shows |
                    |  Analyse PDF     |
                    |  button)         |
                    +--------+---------+
                             |
                     user clicks
                     Analyse PDF
                             |
                             v
                    +------------------+
                    |  Processing State|
                    |                  |
                    |  "Analysing PDF" |
                    |  label shown     |
                    |  while POST      |
                    |  /api/upload is  |
                    |  pending         |
                    |  (may be minutes)|
                    +--------+---------+
                             |
                     HTTP 200 received
                     jobId set
                             |
                             v
                    +------------------+
                    |  Result State    |
                    |                  |
                    |  Left: assembly  |
                    |  thumbnail nav   |
                    |                  |
                    |  Centre: diagram |
                    |  canvas with     |
                    |  hotspot pins    |
                    |                  |
                    |  Right: BOM      |
                    |  panel with      |
                    |  part rows       |
                    +------------------+
```

The result viewer loads the diagram image directly from Cloudinary. Hotspot pins are rendered as SVG elements overlaid on the diagram using pixel coordinates from the result JSON. Clicking a hotspot pin highlights the corresponding BOM row. Clicking a BOM row scrolls the diagram to the corresponding hotspot.

---

## Deployment

### Current Production Stack

```
+-------------------+     VITE_API_URL env var     +-----------------------------+
|                   | ---------------------------> |                             |
|  Vercel           |                              |  Google Cloud Run           |
|                   |                              |  asia-southeast1            |
|  React + Vite     |                              |  Memory: 2 GiB              |
|  Static hosting   |                              |  CPU: 1 (request-based)     |
|  Auto-deploy from |                              |  Concurrency: 1             |
|  GitHub main      |                              |  Timeout: 900s              |
|                   |                              |  Min instances: 0           |
|                   |                              |  Max instances: 2           |
+-------------------+                              +-----------------------------+
                                                              |
                                   +--------------------------+--------------------------+
                                   |                                                     |
                          +--------+--------+                              +-------------+----------+
                          |                 |                              |                        |
                          |  MongoDB Atlas  |                              |  Cloudinary            |
                          |  Singapore      |                              |  CDN                   |
                          |  Free M0 tier   |                              |  diagram image storage |
                          |                 |                              |                        |
                          +-----------------+                              +------------------------+
```

![Backend Request and Processing Flow](images/Exploded%20view%20-%20visual%20selection.png)

### Docker Image

The Dockerfile builds a single image with both Node.js and Python. The build process:

1. Installs system libraries: `libglib2.0`, `libgl1`, `libgomp1`, `libsm6`, `libxext6`, `libxrender-dev` (required by OpenCV and PaddlePaddle).
2. Installs all Python packages from `ai-worker/requirements.txt` including PaddlePaddle and PaddleOCR.
3. Pre-downloads PaddleOCR detection and recognition models by running a one-line Python initialization during the build. Models are stored at `/root/.paddleocr` in the image layer. At runtime, PaddleOCR finds the models already present and does not attempt to download them. This eliminates cold-start latency and the risk of OOM during model initialization.
4. Installs Node.js production dependencies.
5. Copies the backend and ai-worker source.

The image is pushed to Google Artifact Registry and deployed to Cloud Run.

### Cloud Run Request Lifecycle

```
POST /api/upload arrives at Cloud Run
         |
         | Cloud Run allocates CPU (active request)
         |
         v
Node.js creates Job in MongoDB
         |
         v
Node.js spawns Python subprocess
         |
         | [Python runs for 30s - several minutes]
         | [CPU guaranteed because request is active]
         |
         v
Python emits {"status":"done"}
         |
         v
Node.js reads result.json from /tmp
Node.js uploads diagram.png to Cloudinary
Node.js saves Result to MongoDB
Node.js marks Job done
         |
         v
HTTP 200 { jobId, status:'done' } returned
         |
         | Cloud Run may now throttle CPU (no active request)
         | (this is fine — all work is done)
```

---

## Deployment Issues Encountered

### Issue 1 — Render OOM kills due to PaddleOCR memory usage

The initial deployment target was Render. The Starter plan on Render provides 512 MB of RAM. PaddleOCR with PaddlePaddle requires approximately 500 MB to 1 GB of RAM during initialization and inference, which caused the container to be killed by the operating system with a SIGKILL signal (OOM kill) during the first PDF processing request.

Several mitigations were applied to reduce memory pressure:

- The PaddleOCR engine was converted to a module-level singleton so it is initialized once and reused across calls, rather than being created on each OCR request.
- `cpu_threads` was reduced from the default (10) to 4 to reduce the thread stack memory overhead.
- `show_log=False` was set to suppress PaddleOCR's internal logging, which writes to memory buffers.
- Large intermediate image arrays (the preprocessed image, the rendered page pixmap) were explicitly deleted with `del` and followed by `gc.collect()` after each stage to return memory to the Python allocator promptly.
- PaddleOCR models were baked into the Docker image at build time so model downloads do not occur at runtime, preventing a burst of memory usage during cold starts.

Despite these optimizations, 512 MB proved insufficient for reliable operation. The project was migrated to Google Cloud Run with a 2 GiB memory allocation, which resolved the OOM issue.

### Issue 2 — Cloud Run background process CPU throttling

The original upload architecture fired the Python pipeline as a background task (fire-and-forget) and returned the job ID immediately so the frontend could begin polling. This pattern works on traditional servers and on Render, where the process continues running after an HTTP response is sent.

On Google Cloud Run, CPU is only allocated to a container instance during an active HTTP request by default. Returning the HTTP response while Python was still processing caused Cloud Run to throttle or suspend CPU for the instance, halting the Python subprocess mid-pipeline.

The fix was to restructure `POST /api/upload` to await the full pipeline before returning the response. The HTTP request remains open for the entire processing duration (covered by the 900-second timeout). Cloud Run guarantees CPU throughout because the request is active. This also made the upload response directly include the completion status, simplifying the client flow. Request-based billing (the default) became sufficient — instance-based (always-allocated) billing was not needed.

### Issue 3 — Cloudinary 403 errors on diagram image upload

After Cloudinary integration was added, the backend received HTTP 403 responses when attempting to upload diagram images. The cause was an invalid or regenerated API secret: the secret stored in the environment did not match the active credential in the Cloudinary dashboard.

The fix was to regenerate the API secret in the Cloudinary dashboard (Settings — API Keys), update the secret in the backend `.env` file for local development, and update the corresponding secret in the Cloud Run environment variable configuration. The Cloudinary service was also updated to wrap uploads in a try/catch so that a Cloudinary failure does not cause the entire job to fail — the pipeline completes and falls back to the local static file URL if Cloudinary is unavailable.

### Issue 4 — Debian 12 externally-managed Python environment

The Docker base image (node:20-slim) uses Debian 12, which enforces PEP 668 and blocks system-wide `pip install` commands by default. The initial Dockerfile failed at the Python dependency installation step with the error `externally-managed-environment`.

The fix was to add `--break-system-packages` to the `pip3 install` command. This flag is safe inside a Docker container because the container is an isolated environment and there is no risk of breaking the host system's Python installation.

---

## Environment Variables

### Backend (Node.js)

| Variable | Required | Description |
|---|---|---|
| `PORT` | No | HTTP port. Cloud Run injects this automatically. Defaults to 5000. |
| `NODE_ENV` | Yes | Set to `production` in deployed environments. |
| `MONGO_URI` | Yes | MongoDB Atlas connection string. |
| `STORAGE_PATH` | Yes | Path for uploaded PDFs and pipeline outputs. Use `/tmp/explodedview-storage` on Cloud Run. Use `../storage` locally. |
| `PYTHON_EXECUTABLE` | Yes | Python binary. Use `python3` on Linux/Cloud Run. Use the full venv path locally on Windows. |
| `PYTHON_WORKER_PATH` | Yes | Path to `ai-worker/main.py`. Use `/app/ai-worker/main.py` on Cloud Run. |
| `CLOUDINARY_CLOUD_NAME` | No | Cloudinary cloud name. If absent, diagram images are served from the local static path. |
| `CLOUDINARY_API_KEY` | No | Cloudinary API key. |
| `CLOUDINARY_API_SECRET` | No | Cloudinary API secret. |
| `JOB_TTL_DAYS` | No | Days before job files are purged. Defaults to 7. |
| `MAX_UPLOAD_SIZE_MB` | No | Maximum PDF upload size in megabytes. Defaults to 50. |

### AI Worker (Python) — inherited from Node.js process environment

| Variable | Required | Description |
|---|---|---|
| `STORAGE_PATH` | Yes | Same value as the Node.js STORAGE_PATH. Passed via the spawned process environment. |
| `GEMINI_API_KEY` | No | Google AI Studio API key for Gemini Vision recovery. |
| `GEMINI_MODEL` | No | Gemini model name. Defaults to `gemini-2.5-flash`. |
| `LLM_ENABLED` | No | Set to `true` to enable Gemini recovery stage. Defaults to false. |
| `LLM_TIMEOUT_SECONDS` | No | Timeout for Gemini API calls. Defaults to 15. |
| `PDF_RENDER_DPI` | No | DPI for PDF page rendering. Defaults to 300. |
| `DEBUG` | No | Set to `true` to write intermediate images (preprocessed, contours, circles) to disk. Set to `false` in production. |

---

## Local Development

### Prerequisites

- Node.js 20
- Python 3.11 with a virtual environment containing all packages from `ai-worker/requirements.txt`
- MongoDB running locally or a MongoDB Atlas connection string
- (Optional) Cloudinary account for image upload testing

### Setup

```bash
# Install Node.js dependencies
cd backend
npm install

# Create Python virtual environment and install dependencies
cd ../ai-worker
python -m venv venv
venv\Scripts\activate       # Windows
source venv/bin/activate    # Linux / macOS
pip install -r requirements.txt

# Install frontend dependencies
cd ../frontend
npm install
```

### Environment configuration

Copy `backend/.env.example` to `backend/.env` and fill in the values.

Key local values:
```
STORAGE_PATH=../storage
PYTHON_EXECUTABLE=..\ai-worker\venv\Scripts\python.exe   # Windows
PYTHON_EXECUTABLE=../ai-worker/venv/bin/python3           # Linux / macOS
PYTHON_WORKER_PATH=../ai-worker/main.py
```

### Running locally

```bash
# Terminal 1 — backend
cd backend
npm run dev

# Terminal 2 — frontend
cd frontend
npm run dev
```

The Vite dev server runs on port 5173 and proxies `/api` and `/static` requests to the backend on port 5000. Open `http://localhost:5173` in a browser.

The `VITE_API_URL` variable should be empty or absent in local development. The Vite proxy handles routing automatically.
