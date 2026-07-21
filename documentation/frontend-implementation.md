# ExplodedView — Frontend Implementation

> Last updated: 2026-07-15
> Status: Milestone 3 — Phase 1–4 implemented · visual test pending

---

## What This Document Covers

Frontend architecture, component structure, design decisions, and implementation progress for the React workspace. Backend and Python pipeline are documented in `implementation-progress.md`.

---

## Tech Stack

| Tool | Version | Role |
|---|---|---|
| React | 18.3.1 | UI framework |
| Vite | 5.4.8 | Dev server + bundler |
| Tailwind CSS | 3.4.13 | Utility-first styling |
| React Icons | 5.3.0 | Icon set (Feather Icons via `react-icons/fi`) |
| Native fetch | — | HTTP client (no axios) |

**Rules enforced:**
- No separate CSS files — Tailwind only
- No gradients, glassmorphism, excessive shadows, or decorative animations
- No additional icon libraries beyond `react-icons`
- One icon set used throughout: Feather Icons (`fi`)

---

## Design Contract

| Element | Value |
|---|---|
| Background | White (`bg-white`) |
| Primary text / icons | Black / dark gray (`text-gray-900`, `text-gray-800`) |
| Borders / subtle lines | Light gray (`border-gray-100`, `border-gray-200`) |
| Dotted canvas background | `#e5e7eb` dots on white via inline SVG data URL |
| Primary action / active state | Purple (`bg-purple-600`, `text-purple-600`) |
| Errors / failed states | Red (`text-red-500`, `border-red-200`, `bg-red-50`) |
| Unpositioned / inactive | Light gray (`text-gray-300`, `text-gray-400`) |

---

## Project Structure

```
frontend/
├── index.html
├── vite.config.js           ← dev proxy: /api + /static → localhost:5000
├── tailwind.config.js
├── postcss.config.js
├── package.json
└── src/
    ├── main.jsx             ← React root mount
    ├── App.jsx              ← single entry point → <Workspace />
    ├── index.css            ← @tailwind base/components/utilities
    │
    ├── api/
    │   └── pipeline.js      ← uploadPdf(), getJobStatus(), getResult()
    │
    ├── hooks/
    │   ├── useUpload.js     ← manages AbortController, POST /api/upload
    │   └── useJobPoller.js  ← polls GET /api/jobs/:jobId every 2s
    │
    ├── utils/
    │   └── pipelineSteps.js ← ordered step definitions + resolveStepStates()
    │
    └── components/
        ├── workspace/
        │   └── Workspace.jsx        ← single evolving canvas; owns all state
        ├── upload/
        │   ├── DropZone.jsx         ← drag-drop + file browser
        │   └── UploadBar.jsx        ← filename, size, upload button
        ├── pipeline/
        │   └── PipelineTracker.jsx  ← step list with state icons
        ├── viewer/
        │   ├── DiagramCanvas.jsx    ← <img> + <svg> overlay, coordinate scaling
        │   ├── HotspotPin.jsx       ← single SVG pin (circle + number)
        │   └── BomPanel.jsx         ← scrollable BOM list, two-way selection
        └── shared/
            └── ErrorBanner.jsx
```

---

## Workspace State Machine

`Workspace.jsx` owns the entire application state. It transitions through three visual states — no router, no separate pages.

```
upload state
  │  user selects PDF + clicks "Analyse PDF"
  ▼
processing state
  │  useJobPoller polls every 2s; PipelineTracker updates live
  │  on error → ErrorBanner with retry
  ▼
viewer state
  │  result fetched from GET /api/results/:jobId
  │  DiagramCanvas + BomPanel rendered
  │  "New PDF" → resets to upload state
```

State variables in `Workspace.jsx`:
- `file` — selected File object
- `jobId` — set after successful upload
- `selectedRef` — currently highlighted hotspot number (shared between canvas and BOM panel)
- `job` — live poll result from `useJobPoller`
- `result` — final pipeline result document

---

## Phase 1 — Upload Workspace

### DropZone
- Dotted-grid white canvas with a centered dashed-border drop zone
- Drag-and-drop triggers `onDragOver` / `onDrop`
- Click opens a hidden `<input type="file" accept="application/pdf">`
- Turns purple-tinted border while dragging

### UploadBar
- Shows filename + formatted file size after selection
- X button clears selection (resets to DropZone)
- Purple "Analyse PDF" button triggers upload
- Uploading state: replaces button with an animated progress bar + "Uploading…" label

### useUpload hook
- Creates `AbortController` per upload (Stage A cancellation via `abort()`)
- Calls `POST /api/upload` with `FormData`
- On success: calls `onSuccess(jobId)` to transition to processing state
- On `AbortError`: silently swallowed (user-initiated cancel)
- On other errors: sets `error` string for `ErrorBanner`

---

## Phase 2 — Pipeline Tracker

### useJobPoller hook
- Polls `GET /api/jobs/:jobId` every 2000ms using recursive `setTimeout`
- Stops on `status: "done"` or `status: "error"`
- On `"done"`: immediately fetches `GET /api/results/:jobId` and sets `result`
- Cleans up timer on unmount

### pipelineSteps.js
Defines the ordered step sequence and maps each backend `PipelineState` key to a user-friendly label:

| Backend key | Label shown |
|---|---|
| `PAGE_CLASSIFICATION` | Classifying pages |
| `PDF_RENDERING` | Rendering diagram |
| `IMAGE_PREPROCESSING` | Processing image |
| `CIRCLE_DETECTION` | Detecting geometry |
| `CALLOUT_READING` | Reading callouts |
| `BOM_EXTRACTION` | Extracting bill of materials |
| `MAPPING` | Mapping hotspots to parts |
| `LLM_VALIDATION` | Validating results *(optional)* |
| `RESULT_GENERATION` | Generating result |

`resolveStepStates(currentStep, jobStatus)` computes the display state for every step:
- `completed` — behind the current step
- `active` — the current step (pulsing icon)
- `skipped` — optional step that was jumped over (e.g. `LLM_VALIDATION` when all mappings are exact)
- `pending` — ahead of the current step
- All steps become `completed` when `jobStatus === "done"`

### LLM_VALIDATION skip handling
When all 12 mappings are exact (confidence 1.0), Python never emits `LLM_VALIDATION`. The job steps directly from `MAPPING` → `RESULT_GENERATION`. `resolveStepStates` detects that an optional step's index was skipped and marks it `"skipped"` (dash icon, greyed label + "skipped" annotation) rather than leaving it stuck as pending.

### PipelineTracker icons

| State | Icon | Colour |
|---|---|---|
| completed | `FiCheck` | Purple |
| active | `FiCircle` (pulsing) | Purple |
| skipped | `FiMinus` | Light gray |
| failed | `FiX` | Red |
| pending | `FiCircle` | Light gray |

---

## Phase 3 — Diagram Viewer

### DiagramCanvas
- Renders `result.diagramImagePath` as an `<img>` (`/static/outputs/<jobId>/diagram.png` proxied from Express)
- An `<svg>` is absolutely positioned over the image, matching its rendered dimensions
- `updateScale()` computes `scaleX = renderedWidth / imageWidth` and `scaleY = renderedHeight / imageHeight`
- Scale recalculates on `img.onLoad` and `window.resize`
- SVG `viewBox` matches the rendered image pixel size, not the original

### HotspotPin
- SVG `<g>` containing: a larger transparent `<circle>` (hit target), a visible `<circle>`, and a `<text>` label
- Coordinates: `cx = mapping.x * scaleX`, `cy = mapping.y * scaleY`
- Radius: `Math.max(mapping.radius * scaleX, 10)` — enforces minimum visible size
- Selected state: filled purple circle, white text
- Unselected: white fill, dark gray stroke, dark text
- `onClick` calls `onSelectRef` in `Workspace`; clicking the same pin again deselects

---

## Phase 4 — BOM Panel

### BomPanel
- Fixed 320px right panel with `border-l border-gray-100`
- Header: "Bill of Materials" + count summary (`12 positioned · 5 unlocated`)
- Scrollable list of positioned parts built from `result.mappings[].bom[]` — flattened to one row per BOM entry, preserving the `hotspotNumber` reference
- Duplicate refs (e.g. ref 11 → two rows) both appear as separate list entries, both highlight when hotspot 11 is selected
- Selected row: `bg-purple-50 border-purple-300`, auto-scrolls into view via `scrollIntoView`

### BomRow selection
- Clicking a row calls `onSelectRef(row.hotspotNumber)` in Workspace
- Clicking an already-selected row passes `null` → deselects
- Two-way sync: selecting a pin highlights the row; selecting a row highlights the pin

### Unpositioned BOM rows
- Rendered in a separate "Not detected on diagram" section below a divider
- No click interaction — no pin exists for these refs
- Greyed text (`text-gray-400`); part number shown below description

---

## API Contract (Frontend ↔ Backend)

| Call | When | Notes |
|---|---|---|
| `POST /api/upload` | User clicks "Analyse PDF" | `multipart/form-data`, field name `file` |
| `GET /api/jobs/:jobId` | Every 2s during processing | Returns `{ status, pipelineStep, filename, errorMessage }` |
| `GET /api/results/:jobId` | Once, when `status === "done"` | Full result document |
| `GET /static/outputs/:jobId/diagram.png` | In `<img src>` after result loaded | Proxied by Vite dev server to Express |

Vite dev proxy (`vite.config.js`):
```js
proxy: {
  '/api':    'http://localhost:5000',
  '/static': 'http://localhost:5000',
}
```

---

## Milestones

| Phase | Description | Status |
|---|---|---|
| 1 | Upload workspace — DropZone, UploadBar, useUpload | ✅ Built · visual test pending |
| 2 | Pipeline tracker — polling, step states, LLM skip | ✅ Built · visual test pending |
| 3 | Diagram viewer — SVG overlay, coordinate scaling | ✅ Built · visual test pending |
| 4 | BOM panel — two-way selection, unpositioned rows | ✅ Built · visual test pending |
| 5 | Assembly metadata display (title block extraction) | ⏳ After pipeline work |
| 6 | Multi-assembly navigation | ⏳ Future milestone |

---

## Deferred Decisions

| Item | Decision |
|---|---|
| Assembly title | Filename shown as placeholder. True title comes from PDF title block — deferred to pipeline milestone after frontend. |
| Multi-assembly selector | Schema and UI deferred. Frontend `selectedRef` state is designed around one active assembly. |
| Job cancellation (Stage B) | No cancel button implemented. `POST /api/jobs/:jobId/cancel` not built. Deferred. |
| Gemini live path testing | All Bobcat mappings are exact; LLM call never fires. Live fuzzy-match test deferred. |
| Cloudinary / CDN for images | Serving from local Express static. Deferred to Milestone 4. |
