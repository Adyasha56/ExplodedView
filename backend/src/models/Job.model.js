const mongoose = require('mongoose');
const config = require('../config');
const PipelineState = require('../constants/pipeline');

const JobSchema = new mongoose.Schema(
  {
    jobId: {
      type: String,
      required: true,
      unique: true,
      index: true,
    },
    filename: {
      type: String,
      required: true,
    },
    fileSizeBytes: {
      type: Number,
      required: true,
    },
    status: {
      type: String,
      enum: ['pending', 'processing', 'done', 'error'],
      default: 'pending',
      index: true,
    },
    // Current pipeline step — uses PipelineState constants so the value is
    // always one of the known enum members, never a freeform string.
    pipelineStep: {
      type: String,
      enum: Object.values(PipelineState),
      default: PipelineState.UPLOADING,
    },
    errorMessage: {
      type: String,
      default: null,
    },
  },
  {
    timestamps: true, // adds createdAt and updatedAt automatically
  }
);

// TTL index: MongoDB auto-deletes Job documents after JOB_TTL_DAYS days.
// cleanup.service.js handles file deletion before this fires.
JobSchema.index(
  { createdAt: 1 },
  { expireAfterSeconds: config.jobs.ttlDays * 24 * 60 * 60 }
);

module.exports = mongoose.model('Job', JobSchema);
