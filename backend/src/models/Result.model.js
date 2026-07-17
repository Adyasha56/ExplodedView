const mongoose = require('mongoose');

const HotspotSchema = new mongoose.Schema(
  {
    number:           { type: String, required: true },
    x:                { type: Number, required: true },
    y:                { type: Number, required: true },
    radius:           { type: Number, required: true },
    extractionMethod: { type: String, enum: ['pymupdf', 'paddleocr'], required: true },
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

// bom[] contains only visible (non-NOT SHOWN) rows for this hotspot.
const MappingSchema = new mongoose.Schema(
  {
    hotspotNumber: { type: String,      required: true },
    x:             { type: Number,      required: true },
    y:             { type: Number,      required: true },
    radius:        { type: Number,      required: true },
    confidence:    { type: Number, min: 0, max: 1, required: true },
    bom:           { type: [BomRowSchema], required: true },
  },
  { _id: false }
);

const PageMapSchema = new mongoose.Schema(
  {
    diagramPageIndex:         { type: Number, required: true },
    bomPageIndex:             { type: Number, required: true },
    classificationConfidence: { type: String, enum: ['high', 'low'], required: true },
  },
  { _id: false }
);

// One assembly = one diagram + its BOM table, fully processed.
const AssemblySchema = new mongoose.Schema(
  {
    assemblyIndex:     { type: Number,         required: true },
    pageMap:           { type: PageMapSchema,  required: true },
    // Express static URL for this assembly's diagram image.
    // e.g. /static/outputs/<jobId>/assembly_0/diagram.png
    diagramImagePath:  { type: String,         required: true },
    imageWidth:        { type: Number,         required: true },
    imageHeight:       { type: Number,         required: true },
    // Raw BOM record count (all rows excluding header, before any categorization).
    totalParts:        { type: Number,         required: true },
    hotspots:          { type: [HotspotSchema],  default: [] },
    bom:               { type: [BomRowSchema],   default: [] },
    mappings:          { type: [MappingSchema],  default: [] },
    // Hotspots detected on the diagram but not matched to any BOM row.
    unmappedHotspots:  { type: [HotspotSchema],  default: [] },
    // BOM rows whose callout was never detected — no position available.
    unpositionedBomRows: { type: [BomRowSchema], default: [] },
    // BOM rows explicitly marked "NOT SHOWN" — no diagram position by definition.
    notShownBomRows:   { type: [BomRowSchema],   default: [] },
    // Audit log of Gemini validation decisions for this assembly.
    llmValidations:    { type: Array,            default: [] },
  },
  { _id: false }
);

const ResultSchema = new mongoose.Schema(
  {
    jobId:                { type: String, required: true, unique: true, index: true },
    processingDurationMs: { type: Number, required: true },
    // Physical page count of the source PDF — for display as "X / totalPdfPages".
    totalPdfPages:        { type: Number, required: true },
    assemblies:           { type: [AssemblySchema], default: [] },
  },
  {
    timestamps: true,
  }
);

module.exports = mongoose.model('Result', ResultSchema);
