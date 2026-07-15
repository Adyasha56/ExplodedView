const express = require('express');
const router = express.Router();
const uploadMiddleware = require('../middleware/upload.middleware');
const uploadController = require('../controllers/upload.controller');

// multer middleware runs first — validates file type/size and saves to disk.
// If multer rejects the file, it calls next(err) and the controller is skipped.
router.post('/', uploadMiddleware, uploadController.handleUpload);

module.exports = router;
