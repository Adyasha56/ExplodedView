# Use Cases — BOM & Hotspot Handling

Defines how the system must behave across all combinations of hotspot detection and BOM data. These rules govern extraction, mapping, and presentation as separate concerns. Customer data is never altered or silently dropped.

---

## Guiding Principles

- **bom_extractor.py** — preserve every raw row exactly as extracted. Never deduplicate or drop.
- **mapping_engine.py** — establish hotspot-to-record relationships only. No presentation logic.
- **Frontend / result presentation** — only layer where visual consolidation of identical records is permitted. Raw arrays and counts are never modified.
- `totalParts` = number of data rows in the source BOM table, excluding the header, counted before any categorization (NOT SHOWN rows count toward this total).
- Customer data is always right. When in doubt, show more, not less.

---

## Case 1 — Hotspot detected, no BOM match

**Situation:** A callout circle is found on the diagram but no BOM row shares that ref number.

**Current handling:** Stored in `unmappedHotspots[]`.

**Status:** Skipped for now. No UI action required.

---

## Case 2 — BOM row exists, no hotspot detected

**Situation:** The BOM table has a row but no matching callout circle was detected on the diagram.

**Handling:**
- Stored in `unpositionedBomRows[]`.
- Shown in the BOM panel under a **"Not detected on diagram"** section, grayed out.
- No highlight or hotspot interaction — no position to link to.
- Counted in the unmapped tally in the BOM panel subtitle.
- `totalParts` includes these rows.

**Rule:** NOT SHOWN rows must not be counted as unpositioned. The two categories are mutually exclusive.

---

## Case 3 — Duplicate rows, same hotspot (identical records)

**Situation:** The BOM table contains two or more rows that are completely identical — same `refNo`, `partNo`, `description`, and `qty`.

**Handling:**
- `bom_extractor.py` preserves both rows. `totalParts` counts both.
- `mapping_engine.py` maps both rows to the hotspot. `bom[]` inside the mapping contains both.
- **Frontend only:** at render time, collapse to one visual row if `refNo + partNo + description + qty` are all identical. Do not drop, do not alter the raw array.
- If `qty` differs between otherwise identical rows, treat them as distinct and show separately.

**Rule:** Deduplication is visual only. Raw data and counts are never affected.

---

## Case 4 — Same hotspot, genuinely different parts

**Situation:** Multiple BOM rows share the same ref number but have different `partNo` or `description` — these are distinct parts at the same callout position.

**Handling:**
- All rows are mapped to the hotspot and stored in `mappings[].bom[]`.
- All rows are shown in the hotspot popup and in the BOM panel.
- No graying out. No merging.
- This is fully correct behavior — no changes needed.

**Rule:** Never consolidate rows with any differing field. Show all of them.

---

## Case 5 — NOT SHOWN rows

**Situation:** BOM rows whose description contains "NOT SHOWN" — these parts exist in the BOM but have no physical location on the diagram by design.

**Handling:**
- `mapping_engine.py` splits these out of the hotspot's `bom[]` into `not_shown_bom_rows[]`.
- Stored in `notShownBomRows[]` at the assembly level.
- Shown in the BOM panel under a **"Not shown on diagram"** section with an amber "Not shown" badge.
- Count displayed in the BOM panel subtitle as `N not shown`.
- `totalParts` includes these rows (they are valid source records).
- Must not appear in `unpositionedBomRows[]` — the two lists are mutually exclusive.

---

## Page Numbering

**Rule:** Page identity must always come from the physical position of the page within the PDF file — never from any page label, number, or text detected inside the page content (e.g. "2A", "2B", "Page 3 of 10").

**Reason:** Printed page labels can be non-numeric, duplicated, or absent. Physical index is always reliable.

**Implementation:**
- `totalPdfPages` = `len(doc)` captured in `main.py` after opening the PDF. Stored at the top level of the result (not per assembly).
- `pageMap.diagramPageIndex` and `pageMap.bomPageIndex` are 0-based physical page positions.
- **Display format:** `p.{index + 1} / {totalPdfPages}` — e.g. "diagram p.3/10 · BOM p.4/10".
- Shown in the assembly header when more than one assembly is present.

---

## BOM Panel Subtitle — Metric Definitions

| Label | Source | Definition |
|---|---|---|
| `N total` | `assembly.totalParts` | Raw BOM row count before any categorization |
| `N unlocated` | `assembly.unpositionedBomRows.length` | BOM rows with no detected hotspot (excludes NOT SHOWN) |
| `N not shown` | `assembly.notShownBomRows.length` | Rows explicitly marked NOT SHOWN in the BOM |

---

## Files Involved

| Layer | File | Responsibility |
|---|---|---|
| Extraction | `ai-worker/modules/bom_extractor.py` | Raw rows only — never modified for these cases |
| Mapping | `ai-worker/modules/mapping_engine.py` | Splits NOT SHOWN; maps hotspots to raw rows |
| Pipeline | `ai-worker/main.py` | Computes `total_parts` and `total_pdf_pages` |
| Serialisation | `ai-worker/modules/result_writer.py` | Writes `totalParts` per assembly, `totalPdfPages` at top level |
| Schema | `backend/src/models/Result.model.js` | Stores both new fields |
| UI — BOM panel | `frontend/src/components/viewer/BomPanel.jsx` | Visual dedup, correct subtitle counts, NOT SHOWN section |
| UI — Popup | `frontend/src/components/viewer/DiagramCanvas.jsx` | Visual dedup in hotspot popup only |
| UI — Header | `frontend/src/components/viewer/AssemblySection.jsx` | Physical page number display |
