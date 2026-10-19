const Job = require('../models/Job.model');
const logger = require('../utils/logger');
const jobEvents = require('../utils/jobEvents');

const TERMINAL_STATUSES = new Set(['done', 'error']);

function toPayload(job) {
  return {
    jobId: job.jobId,
    filename: job.filename,
    status: job.status,
    pipelineStep: job.pipelineStep,
    errorMessage: job.errorMessage,
    createdAt: job.createdAt,
    updatedAt: job.updatedAt,
  };
}

/**
 * GET /api/jobs/:jobId/stream
 *
 * Server-Sent Events stream of job status updates, replacing client-side polling.
 * Sends the current state immediately, then pushes an event each time
 * python.bridge.js records a pipeline step/done/error, until a terminal status.
 */
exports.streamJobStatus = async (req, res, next) => {
  try {
    const { jobId } = req.params;

    const job = await Job.findOne({ jobId }).lean();
    if (!job) {
      return res.status(404).json({ error: `Job not found: ${jobId}` });
    }

    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      // Disable response buffering on proxies in front of Cloud Run.
      'X-Accel-Buffering': 'no',
    });

    const send = (payload) => {
      res.write(`data: ${JSON.stringify(toPayload(payload))}\n\n`);
    };

    send(job);

    if (TERMINAL_STATUSES.has(job.status)) {
      return res.end();
    }

    const onUpdate = (updatedJob) => {
      if (!updatedJob) return;
      send(updatedJob);
      if (TERMINAL_STATUSES.has(updatedJob.status)) {
        jobEvents.off(jobId, onUpdate);
        res.end();
      }
    };

    jobEvents.on(jobId, onUpdate);

    req.on('close', () => {
      jobEvents.off(jobId, onUpdate);
    });

  } catch (err) {
    next(err);
  }
};
