const { EventEmitter } = require('events');

// In-process pub/sub: python.bridge.js emits job updates here as they happen,
// jobs.controller.js's SSE stream subscribes per-jobId to push them to clients.
const jobEvents = new EventEmitter();
jobEvents.setMaxListeners(0);

module.exports = jobEvents;
