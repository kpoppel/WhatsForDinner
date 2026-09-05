/**
 * Coalesce same-turn render requests and reject revisions older than the last
 * committed render. Screen modules retain ownership of their DOM renderer.
 */
export function createRenderScheduler({ render, getRevision, onRender } = {}) {
  if (typeof render !== "function") {
    throw new TypeError("render must be a function");
  }

  let pending = null;
  let scheduled = false;
  let latestRevision = -1;
  let hasRendered = false;
  let renderCount = 0;

  function currentRevision() {
    return typeof getRevision === "function" ? getRevision() : 0;
  }

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
