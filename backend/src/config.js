require('dotenv').config();
const path = require('path');
const fs = require('fs');

const config = {
  server: {
    port: parseInt(process.env.PORT, 10) || 5000,
    nodeEnv: process.env.NODE_ENV || 'development',
  },

  db: {
    uri: process.env.MONGO_URI || 'mongodb://localhost:27017/exploded_view',
  },

  storage: {
    // Resolve relative to the backend/ directory (one level above this file).
    // STORAGE_PATH in .env is relative to backend/:  "../storage" → ExplodedView/storage
    root: path.resolve(__dirname, '..', process.env.STORAGE_PATH || '../storage'),
    get uploads() { return path.join(this.root, 'uploads'); },
    get outputs() { return path.join(this.root, 'outputs'); },
  },

  python: {
    // If PYTHON_EXECUTABLE contains a path separator it is resolved relative to
    // backend/; otherwise treated as a command name on PATH (e.g. "python3").
    executable: process.env.PYTHON_EXECUTABLE && process.env.PYTHON_EXECUTABLE.includes(path.sep)
      ? path.resolve(__dirname, '..', process.env.PYTHON_EXECUTABLE)
      : (process.env.PYTHON_EXECUTABLE || 'python'),
    workerPath: path.resolve(__dirname, '..', process.env.PYTHON_WORKER_PATH || '../ai-worker/main.py'),
  },

  jobs: {
    ttlDays: parseInt(process.env.JOB_TTL_DAYS, 10) || 7,
  },

  upload: {
    maxSizeBytes: (parseInt(process.env.MAX_UPLOAD_SIZE_MB, 10) || 50) * 1024 * 1024,
    allowedMimeTypes: ['application/pdf'],
    allowedExtensions: ['.pdf'],
  },
};

// Ensure storage dirs exist at startup (important when STORAGE_PATH points to /tmp)
fs.mkdirSync(config.storage.uploads, { recursive: true });
fs.mkdirSync(config.storage.outputs, { recursive: true });

module.exports = config;
