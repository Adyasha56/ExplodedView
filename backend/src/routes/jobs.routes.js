const express = require('express');
const router = express.Router();
const jobsController = require('../controllers/jobs.controller');

// GET /api/jobs/:jobId/stream — Server-Sent Events stream of job status updates
router.get('/:jobId/stream', jobsController.streamJobStatus);

module.exports = router;
