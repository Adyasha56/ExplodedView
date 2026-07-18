const { spawn } = require('child_process');
const readline = require('readline');
const fs = require('fs');
const path = require('path');

const config = require('../config');
const logger = require('../utils/logger');
const PipelineState = require('../constants/pipeline');
const Job = require('../models/Job.model');
const Result = require('../models/Result.model');
const cleanupService = require('./cleanup.service');
const cloudinaryService = require('./cloudinary.service');

// Python emits lowercase_underscore step names; normalise to PipelineState constants.
const STEP_MAP = {
  page_classification:  PipelineState.PAGE_CLASSIFICATION,
  pdf_rendering:        PipelineState.PDF_RENDERING,
  image_preprocessing:  PipelineState.IMAGE_PREPROCESSING,
  circle_detection:     PipelineState.CIRCLE_DETECTION,
  callout_reading:      PipelineState.CALLOUT_READING,
  bom_extraction:       PipelineState.BOM_EXTRACTION,
  mapping:              PipelineState.MAPPING,
  llm_validation:       PipelineState.LLM_VALIDATION,
  result_writing:       PipelineState.RESULT_GENERATION,
};

exports.runPipeline = (jobId) => {
  return new Promise(async (resolve, reject) => {
    const startTime = Date.now();
    logger.info(`[${jobId}] Spawning Python worker`);

    await Job.findOneAndUpdate(
      { jobId },
      { status: 'processing', pipelineStep: PipelineState.PAGE_CLASSIFICATION }
    );

    const args = [
      config.python.workerPath,
      '--job-id', jobId,
      '--storage-path', config.storage.root,
    ];

    const pythonProcess = spawn(config.python.executable, args, {
      env: { ...process.env },
      // Run from the ai-worker directory so Python can resolve its relative imports
      // (config.py, modules/, utils/, etc. are all relative to ai-worker/).
      cwd: path.dirname(config.python.workerPath),
    });

    // ── stdout: line-by-line JSON status messages from Python ───────────────
    const rl = readline.createInterface({ input: pythonProcess.stdout });

    rl.on('line', async (line) => {
      line = line.trim();
      if (!line) return;

      let msg;
      try {
        msg = JSON.parse(line);
      } catch {
        // Python printed a non-JSON debug line — log it and move on.
        logger.debug(`[${jobId}] Python stdout (raw): ${line}`);
        return;
      }

      if (msg.status === 'processing' && msg.step) {
        const pipelineStep = STEP_MAP[msg.step] ?? msg.step;
        logger.info(`[${jobId}] Pipeline step: ${pipelineStep}`);
        await Job.findOneAndUpdate({ jobId }, { pipelineStep }).catch((err) => {
          logger.error(`[${jobId}] Failed to update pipelineStep: ${err.message}`);
        });
      }

      if (msg.status === 'done') {
        const durationMs = Date.now() - startTime;
        logger.info(`[${jobId}] Pipeline complete in ${durationMs}ms`);
        await _handleSuccess(jobId, durationMs).then(resolve).catch(reject);
      }

      if (msg.status === 'error') {
        logger.error(`[${jobId}] Pipeline error: ${msg.message}`);
        await _handleFailure(jobId, msg.message || 'Unknown pipeline error').catch(() => {});
        reject(new Error(msg.message));
      }
    });

    // ── stderr: Python tracebacks and logging output ─────────────────────────
    pythonProcess.stderr.on('data', (data) => {
      // Python logger writes to stdout; stderr usually means an unhandled crash.
      logger.warn(`[${jobId}] Python stderr: ${data.toString().trim()}`);
    });

    // ── Process exit ──────────────────────────────────────────────────────────
    pythonProcess.on('close', async (code) => {
      if (code !== 0) {
        // Process crashed without emitting a {"status":"error"} line.
        const msg = `Python process exited with code ${code}`;
        logger.error(`[${jobId}] ${msg}`);
        await _handleFailure(jobId, msg).catch(() => {});
        reject(new Error(msg));
      }
    });

    pythonProcess.on('error', async (err) => {
      // spawn itself failed — most likely PYTHON_EXECUTABLE not found.
      const msg = `Failed to spawn Python: ${err.message}`;
      logger.error(`[${jobId}] ${msg}`);
      await _handleFailure(jobId, msg).catch(() => {});
      reject(err);
    });
  });
};

// ── Private helpers ───────────────────────────────────────────────────────────

async function _handleSuccess(jobId, durationMs) {
  const resultPath = path.join(config.storage.outputs, jobId, 'result.json');

  if (!fs.existsSync(resultPath)) {
    throw new Error(`result.json not found at expected path: ${resultPath}`);
  }

  const raw = fs.readFileSync(resultPath, 'utf-8');
  let resultData;
  try {
    resultData = JSON.parse(raw);
  } catch (err) {
    throw new Error(`result.json is not valid JSON: ${err.message}`);
  }

  // Upload each diagram to Cloudinary (prod) or fall back to Express static URL (local dev).
  if (Array.isArray(resultData.assemblies)) {
    resultData.assemblies = await Promise.all(
      resultData.assemblies.map(async (assembly, index) => {
        const relativePath = assembly.diagramImagePath.replace(/\\/g, '/');
        const localPath    = path.join(config.storage.root, relativePath);

        const cloudinaryUrl = await cloudinaryService.uploadDiagram(localPath, jobId, index);

        return {
          ...assembly,
          diagramImagePath: cloudinaryUrl || '/static/' + relativePath,
        };
      })
    );
  }

  await Result.create({ ...resultData, jobId });
  await Job.findOneAndUpdate(
    { jobId },
    { status: 'done', pipelineStep: PipelineState.COMPLETED }
  );

  logger.info(`[${jobId}] Result saved to MongoDB`);

  cleanupService.cleanupJobFiles(jobId).catch((err) => {
    logger.warn(`[${jobId}] Cleanup warning: ${err.message}`);
  });
}

async function _handleFailure(jobId, message) {
  await Job.findOneAndUpdate(
    { jobId },
    { status: 'error', pipelineStep: PipelineState.FAILED, errorMessage: message }
  );
}
