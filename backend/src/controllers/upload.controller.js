const path = require('path');
const Job = require('../models/Job.model');
const PipelineState = require('../constants/pipeline');
const pythonBridge = require('../services/python.bridge');
const logger = require('../utils/logger');

/**
 * POST /api/upload
 *
 * Flow:
 *   1. multer middleware (upload.middleware.js) has already saved the file to
 *      storage/uploads/<jobId>.pdf and attached req.jobId + req.file.
 *   2. Create Job document in MongoDB.
 *   3. Fire-and-forget: start the Python pipeline asynchronously.
 *   4. Immediately return { jobId, status } — client polls for progress.
 *
 * The controller is intentionally thin. File handling is multer's job.
 * Pipeline orchestration is python.bridge's job.
 */
exports.handleUpload = async (req, res, next) => {
  // multer errors (wrong file type, size exceeded) arrive as the first argument
  // to the error-handling middleware — they are not caught here. multer calls
  // next(err) automatically when fileFilter rejects a file.

  try {
    if (!req.file) {
      return res.status(400).json({ error: 'No file received. Send a PDF as multipart field "file".' });
    }

    const { jobId } = req;
    const { originalname, size } = req.file;

    logger.info(`[${jobId}] Upload received — file: "${originalname}", size: ${(size / 1024).toFixed(1)} KB`);

    // Create the Job record. Status starts at "pending"; bridge will update it.
    const job = await Job.create({
      jobId,
      filename: originalname,
      fileSizeBytes: size,
      status: 'pending',
      pipelineStep: PipelineState.UPLOADING,
    });

    logger.info(`[${jobId}] Job created in MongoDB`);

    // Fire-and-forget — do NOT await. The client will poll /api/jobs/:jobId.
    // Any errors inside runPipeline are caught there and written to the Job doc.
    pythonBridge.runPipeline(jobId).catch((err) => {
      logger.error(`[${jobId}] Unhandled pipeline error: ${err.message}`);
    });

    return res.status(202).json({
      jobId,
      status: job.status,
      message: 'File accepted. Poll /api/jobs/:jobId for progress.',
    });

  } catch (err) {
    next(err);
  }
};
