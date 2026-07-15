const Job = require('../models/Job.model');
const logger = require('../utils/logger');

/**
 * GET /api/jobs/:jobId
 *
 * Returns the current status and pipeline step of a job.
 * Frontend polls this endpoint until status = "done" or "error".
 */
exports.getJobStatus = async (req, res, next) => {
  try {
    const { jobId } = req.params;

    const job = await Job.findOne({ jobId }).lean();

    if (!job) {
      return res.status(404).json({ error: `Job not found: ${jobId}` });
    }

    return res.json({
      jobId: job.jobId,
      filename: job.filename,
      status: job.status,
      pipelineStep: job.pipelineStep,
      errorMessage: job.errorMessage,
      createdAt: job.createdAt,
      updatedAt: job.updatedAt,
    });

  } catch (err) {
    next(err);
  }
};
