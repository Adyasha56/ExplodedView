const express = require('express');
const router = express.Router();
const resultsController = require('../controllers/results.controller');

// GET /api/results/:jobId — fetch full pipeline result document
router.get('/:jobId', resultsController.getResult);

module.exports = router;
