const multer = require('multer');
const path = require('path');
const fs = require('fs');
const { v4: uuidv4 } = require('uuid');
const config = require('../config');
const logger = require('../utils/logger');

// Ensure uploads directory exists at startup — multer will not create it.
if (!fs.existsSync(config.storage.uploads)) {
  fs.mkdirSync(config.storage.uploads, { recursive: true });
}

const storage = multer.diskStorage({
  destination: (_req, _file, cb) => {
    cb(null, config.storage.uploads);
  },

  filename: (req, _file, cb) => {
    // Generate a UUID here so both multer and the controller share the same jobId
    // without a two-step rename. Attach it to req so the controller can read it.
    const jobId = uuidv4();
    req.jobId = jobId;
    cb(null, `${jobId}.pdf`);
  },
});

// File filter: reject anything that is not a PDF before it touches the disk.
const fileFilter = (_req, file, cb) => {
  const ext = path.extname(file.originalname).toLowerCase();
  const isValidMime = config.upload.allowedMimeTypes.includes(file.mimetype);
  const isValidExt = config.upload.allowedExtensions.includes(ext);

  if (isValidMime && isValidExt) {
    cb(null, true);
  } else {
    logger.warn(`Rejected upload — invalid file type: ${file.mimetype} / ${file.originalname}`);
    cb(new Error('Only PDF files are accepted.'), false);
  }
};

const upload = multer({
  storage,
  fileFilter,
  limits: {
    fileSize: config.upload.maxSizeBytes,
    files: 1,
  },
});

// Exported as a single-field upload middleware for the 'file' field.
// Usage in routes: router.post('/', uploadMiddleware, controller)
module.exports = upload.single('file');
