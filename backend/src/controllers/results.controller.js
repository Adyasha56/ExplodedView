const Result = require('../models/Result.model');
const Job = require('../models/Job.model');
const logger = require('../utils/logger');

/**
 * GET /api/results/:jobId
 *
 * Returns the full pipeline result document.
 * Only available after job status = "done".
 * Returns 404 if job doesn't exist, 409 if job is not yet complete.
 */
exports.getResult = async (req, res, next) => {
  try {
    const { jobId } = req.params;

    // Verify the job exists and is in a terminal state before querying results.
    const job = await Job.findOne({ jobId }).lean();

    if (!job) {
      return res.status(404).json({ error: `Job not found: ${jobId}` });
    }

    if (job.status === 'error') {
      return res.status(422).json({
        error: 'Pipeline failed for this job.',
        message: job.errorMessage,
      });
    }

    if (job.status !== 'done') {
      return res.status(409).json({
        error: 'Result not ready yet.',
        status: job.status,
        pipelineStep: job.pipelineStep,
      });
    }

    const result = await Result.findOne({ jobId }).lean();

    if (!result) {
      // Job is marked done but result doc is missing — data inconsistency.
      logger.error(`[${jobId}] Job is "done" but Result document is missing`);
      return res.status(500).json({ error: 'Result document not found despite job completion.' });
    }

    const totalMappings = result.assemblies.reduce((n, a) => n + a.mappings.length, 0);
    const totalUnmapped = result.assemblies.reduce((n, a) => n + a.unmappedHotspots.length, 0);
    const totalUnpositioned = result.assemblies.reduce((n, a) => n + a.unpositionedBomRows.length, 0);
    logger.info(
      `[${jobId}] Result fetched — ${result.assemblies.length} assembly(ies), ` +
      `${totalMappings} mappings, ${totalUnmapped} unmapped hotspots, ` +
      `${totalUnpositioned} unpositioned BOM rows`
    );

    return res.json(result);

  } catch (err) {
    next(err);
  }
};
