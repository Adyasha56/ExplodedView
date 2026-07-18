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
// Returns null when Cloudinary is not configured (local dev fallback).
exports.uploadDiagram = async (localPath, jobId, assemblyIndex) => {
  if (!isConfigured) return null;

  const result = await cloudinary.uploader.upload(localPath, {
    folder:        `explodedview/${jobId}`,
    public_id:     `assembly_${assemblyIndex}`,
    resource_type: 'image',
    overwrite:     true,
  });

  logger.info(`[${jobId}] Diagram uploaded to Cloudinary: ${result.secure_url}`);
  return result.secure_url;
};
