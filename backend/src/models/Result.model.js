const mongoose = require('mongoose');

const HotspotSchema = new mongoose.Schema(
  {
    number:          { type: String, required: true },
    x:               { type: Number, required: true },
    y:               { type: Number, required: true },
    radius:          { type: Number, required: true },
    extractionMethod:{ type: String, enum: ['pymupdf', 'paddleocr'], required: true },
  },
  { _id: false }
);

const BomRowSchema = new mongoose.Schema(
  {
    refNo:       { type: String, required: true },
    partNo:      { type: String, default: null },
    description: { type: String, default: null },
    qty:         { type: Number, default: null },
  },
  { _id: false }
);

// One mapping object per detected hotspot.
// bom[] is always an array: one entry for normal refs, multiple for duplicate refs
// (e.g. ref 11 appears twice in the BOM — both rows land in the same mapping).
const MappingSchema = new mongoose.Schema(
  {
    hotspotNumber: { type: String, required: true },
    x:             { type: Number, required: true },
    y:             { type: Number, required: true },
    radius:        { type: Number, required: true },
    confidence:    { type: Number, min: 0, max: 1, required: true },
    bom:           { type: [BomRowSchema], required: true },
  },
  { _id: false }
);

const ResultSchema = new mongoose.Schema(
  {
    jobId:                { type: String, required: true, unique: true, index: true },
    // Artifact-relative URL served by Express static middleware.
    // e.g. /static/outputs/<jobId>/diagram.png
    diagramImagePath:     { type: String, required: true },
    imageWidth:           { type: Number, required: true },
    imageHeight:          { type: Number, required: true },
    processingDurationMs: { type: Number, required: true },
    pageMap: {
      diagramPageIndex:        { type: Number, required: true },
      bomPageIndex:            { type: Number, required: true },
      classificationConfidence:{ type: String, enum: ['high', 'low'], required: true },
    },
    hotspots:             { type: [HotspotSchema],  default: [] },
    bom:                  { type: [BomRowSchema],   default: [] },
    mappings:             { type: [MappingSchema],  default: [] },
    // Hotspots detected on the diagram but not matched to any BOM row.
    unmappedHotspots:     { type: [HotspotSchema],  default: [] },
    // BOM rows that exist in the document but whose callout was never
    // detected by OCR — no diagram position is available for these.
    unpositionedBomRows:  { type: [BomRowSchema],   default: [] },
    // Audit log of all Gemini validation decisions (empty when LLM is disabled).
    llmValidations:       { type: Array,             default: [] },
  },
  {
    timestamps: true,
  }
);

module.exports = mongoose.model('Result', ResultSchema);
