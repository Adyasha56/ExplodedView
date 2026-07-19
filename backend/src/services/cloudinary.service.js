const cloudinary = require('cloudinary').v2;
const logger = require('../utils/logger');

const isConfigured = !!(
  process.env.CLOUDINARY_CLOUD_NAME &&
  process.env.CLOUDINARY_API_KEY &&
  process.env.CLOUDINARY_API_SECRET
);

if (isConfigured) {
  cloudinary.config({
    cloud_name: process.env.CLOUDINARY_CLOUD_NAME,
    api_key:    process.env.CLOUDINARY_API_KEY,
    api_secret: process.env.CLOUDINARY_API_SECRET,
  });
}

exports.isConfigured = isConfigured;

// Uploads a local diagram image to Cloudinary and returns the secure URL.
// Returns null on any failure so the caller can fall back to a local static URL.
// A Cloudinary failure is non-critical — the pipeline result is already written to disk.
exports.uploadDiagram = async (localPath, jobId, assemblyIndex) => {
  if (!isConfigured) {
    logger.info(`[${jobId}] Cloudinary not configured — using local static URL for assembly_${assemblyIndex}`);
    return null;
  }

  logger.info(`[${jobId}] Uploading assembly_${assemblyIndex} to Cloudinary (cloud: ${process.env.CLOUDINARY_CLOUD_NAME})`);
  try {
    const result = await cloudinary.uploader.upload(localPath, {
      folder:        `explodedview/${jobId}`,
      public_id:     `assembly_${assemblyIndex}`,
      resource_type: 'image',
      overwrite:     true,
    });
    logger.info(`[${jobId}] Cloudinary upload OK → ${result.secure_url}`);
    return result.secure_url;
  } catch (err) {
    logger.warn(
      `[${jobId}] Cloudinary upload failed for assembly_${assemblyIndex} ` +
      `(${err.message}) — falling back to local static URL`
    );
    return null;
  }
};
