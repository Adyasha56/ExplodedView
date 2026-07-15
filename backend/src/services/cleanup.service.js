const fs = require('fs');
const path = require('path');
const config = require('../config');
const logger = require('../utils/logger');

/**
 * cleanupJobFiles(jobId)
 *
 * Called after a job reaches "done" status.
 * Deletes temporary files that are no longer needed, keeps what the frontend needs.
 *
 * DELETES:
 *   storage/uploads/<jobId>.pdf           — raw PDF, pipeline has finished with it
 *   storage/outputs/<jobId>/preprocessed.png — debug artifact, not served to frontend
 *
 * KEEPS:
 *   storage/outputs/<jobId>/diagram.png   — served to frontend via /static/outputs
 *   storage/outputs/<jobId>/result.json   — read by results controller (already in MongoDB too)
 *   storage/outputs/<jobId>/pages/        — kept for debugging; remove in production if needed
 *
 * In production, set DEBUG=false in ai-worker/.env so intermediate artifacts
 * are not written in the first place.
 */
exports.cleanupJobFiles = async (jobId) => {
  logger.info(`[${jobId}] Running post-job file cleanup`);

  const toDelete = [
    path.join(config.storage.uploads, `${jobId}.pdf`),
    path.join(config.storage.outputs, jobId, 'preprocessed.png'),
  ];

  for (const filePath of toDelete) {
    _deleteIfExists(filePath, jobId);
  }
};

/**
 * purgeJobOutputDir(jobId)
 *
 * Removes the entire outputs/<jobId>/ directory.
 * Called when a job document expires from MongoDB (TTL) and all associated
 * files should be removed from disk.
 *
 * Note: MongoDB TTL expiry fires asynchronously and does not trigger Node.js
 * code. Call this explicitly when handling expired job cleanup via a scheduled
 * task or a pre-query hook, depending on your operational setup.
 */
exports.purgeJobOutputDir = async (jobId) => {
  const outputDir = path.join(config.storage.outputs, jobId);

  if (fs.existsSync(outputDir)) {
    fs.rmSync(outputDir, { recursive: true, force: true });
    logger.info(`[${jobId}] Purged output directory: ${outputDir}`);
  } else {
    logger.debug(`[${jobId}] Output directory already absent, skipping purge`);
  }
};

// ── Private helpers ────────────────────────────────────────────────────────────

function _deleteIfExists(filePath, jobId) {
  if (fs.existsSync(filePath)) {
    fs.unlinkSync(filePath);
    logger.debug(`[${jobId}] Deleted: ${filePath}`);
  } else {
    logger.debug(`[${jobId}] Already absent, skipping: ${filePath}`);
  }
}
