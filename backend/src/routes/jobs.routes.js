const express = require('express');
const router = express.Router();
const jobsController = require('../controllers/jobs.controller');

// GET /api/jobs/:jobId — poll job status and current pipeline step
router.get('/:jobId', jobsController.getJobStatus);

module.exports = router;
