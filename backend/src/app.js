require('dotenv').config();
const express = require('express');
const cors = require('cors');
const mongoose = require('mongoose');

const config = require('./config');
const logger = require('./utils/logger');
const uploadRoutes = require('./routes/upload.routes');
const jobsRoutes = require('./routes/jobs.routes');
const resultsRoutes = require('./routes/results.routes');

const app = express();

app.use(cors());
app.use(express.json());

// Frontend fetches diagram images at GET /static/outputs/<jobId>/diagram.png
app.use('/static/outputs', express.static(config.storage.outputs));

app.use('/api/upload', uploadRoutes);
app.use('/api/jobs', jobsRoutes);
app.use('/api/results', resultsRoutes);

app.get('/health', (_req, res) => {
  res.json({
    status: 'ok',
    env: config.server.nodeEnv,
    storage: config.storage.root,
  });
});

app.use((_req, res) => {
  res.status(404).json({ error: 'Route not found' });
});

// Catches errors from controllers (next(err)) and multer rejections.
// eslint-disable-next-line no-unused-vars
app.use((err, _req, res, _next) => {
  // Multer sends specific error types we can surface cleanly.
  if (err.code === 'LIMIT_FILE_SIZE') {
    return res.status(413).json({
      error: `File too large. Maximum allowed size is ${config.upload.maxSizeBytes / 1024 / 1024} MB.`,
    });
  }
  if (err.message === 'Only PDF files are accepted.') {
    return res.status(415).json({ error: err.message });
  }

  logger.error(err);
  res.status(err.status || 500).json({
    error: err.message || 'Internal server error',
  });
});

mongoose
  .connect(config.db.uri)
  .then(() => {
    logger.info(`MongoDB connected`);
    app.listen(config.server.port, '0.0.0.0', () => {
      logger.info(`Server listening on port ${config.server.port} [${config.server.nodeEnv}]`);
      logger.info(`Storage root → ${config.storage.root}`);
      logger.info('Routes mounted:');
      logger.info('  POST /api/upload');
      logger.info('  GET  /api/jobs/:jobId');
      logger.info('  GET  /api/results/:jobId');
      logger.info('  GET  /static/outputs/:jobId/diagram.png');
      logger.info('  GET  /health');
    });
  })
  .catch((err) => {
    logger.error(`MongoDB connection failed: ${err.message}`);
    process.exit(1);
  });
