/**
 * Opt-in, bounded in-memory diagnostics for API, sync, and render timings.
 * Metrics are exposed to developer hooks only; this module never persists or
 * transmits them.
 */
const MAX_METRICS = 200;
const metrics = [];
const enabled = typeof window !== "undefined" && window.WFD_PERFORMANCE_METRICS_ENABLED === true;

/** Buffer one bounded performance metric for diagnostics and server-free review. */
function record(kind, metric) {
  if (!enabled || !metric || typeof metric !== "object") {
    return;
  }
  const entry = { kind, ...metric };
  metrics.push(entry);
  if (metrics.length > MAX_METRICS) {
    metrics.shift();
  }
  window.dispatchEvent(new CustomEvent("wfd:performance-metric", { detail: entry }));
}

window.WFD_recordApiMetric = (metric) => record("api", metric);
window.WFD_recordRenderMetric = (metric) => record("render", metric);
window.WFD_recordSyncMetric = (metric) => record("sync", metric);
window.WFD_getPerformanceMetrics = () => metrics.slice();
window.WFD_clearPerformanceMetrics = () => metrics.splice(0, metrics.length);