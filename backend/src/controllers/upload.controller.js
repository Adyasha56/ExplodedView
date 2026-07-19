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
 *   3. Await the Python pipeline — HTTP request stays open until pipeline completes.
 *      This guarantees CPU allocation on Cloud Run for the full pipeline duration.
 *   4. Return { jobId, status } when done, or an error response if the pipeline fails.
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
    await Job.create({
      jobId,
      filename: originalname,
      fileSizeBytes: size,
      status: 'pending',
      pipelineStep: PipelineState.UPLOADING,
    });

    logger.info(`[${jobId}] Job created in MongoDB`);

    // Await the pipeline — keeps the HTTP request open so Cloud Run allocates
    // CPU for the full duration. On failure, python.bridge has already marked
    // the job as 'error' in MongoDB before rejecting, so it is never stuck.
    await pythonBridge.runPipeline(jobId);

    return res.status(200).json({
      jobId,
      status: 'done',
    });

  } catch (err) {
    // Pipeline errors are already written to the Job document by python.bridge.
    // Return an error response so the client knows the upload failed.
    const jobId = req.jobId;
    if (jobId) {
      logger.error(`[${jobId}] Pipeline failed — returning error response: ${err.message}`);
      return res.status(500).json({
        jobId,
        status: 'error',
        error: err.message || 'Pipeline failed.',
      });
    }
    next(err);
  }
};
