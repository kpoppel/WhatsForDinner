/**
 * Coalesce same-turn render requests and reject revisions older than the last
 * committed render. Screen modules retain ownership of their DOM renderer.
 */
/** Create a frame-coalescing scheduler that drops stale render generations. */
export function createRenderScheduler({ render, getRevision, onRender } = {}) {
  if (typeof render !== "function") {
    throw new TypeError("render must be a function");
  }

  let pending = null;
  let scheduled = false;
  let latestRevision = -1;
  let hasRendered = false;
  let renderCount = 0;

  /** Read the current store revision without assuming a particular caller. */
  function currentRevision() {
    return typeof getRevision === "function" ? getRevision() : 0;
  }

  /** Flush the newest queued request and report its render metadata. */
  function flush() {
    scheduled = false;
    const request = pending;
    pending = null;
    if (!request || request.revision < latestRevision) {
      return;
    }
    latestRevision = request.revision;
    hasRendered = true;
    render(request);
    renderCount += 1;
    if (typeof onRender === "function") {
      onRender({
        ...request,
        renderCount,
        renderedAt: Date.now(),
      });
    }
  }

  function request({ source = "unknown", revision = currentRevision(), force = false } = {}) {
    /** Queue the newest render request and coalesce work into one animation frame. */
    if (!Number.isInteger(revision)) {
      revision = currentRevision();
    }
    if (!force && hasRendered && revision === latestRevision && !pending) {
      return false;
    }
    if (revision < latestRevision) {
      return false;
    }
    pending = {
      source,
      revision,
      force,
      requestedAt: Date.now(),
      requestedPerformanceAt: performance.now(),
    };
    if (!scheduled) {
      scheduled = true;
      queueMicrotask(flush);
    }
    return true;
  }

  return {
    request,
    flush,
    getRenderCount: () => renderCount,
    getLatestRevision: () => latestRevision,
  };
}
