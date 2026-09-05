/**
 * Serialize shopping pushes, coalesce refreshes, and assign generations used to
 * prevent an older refresh from replacing a newer optimistic mutation.
 */
export function createSyncCoordinator({ onStatus }) {
  let refreshInFlight = null;
  let pushInFlight = null;
  let pushKey = null;
  const queuedPushes = [];
  let generation = 0;
  let pushStartedAt = null;

  function report(status, error = null) {
    if (typeof onStatus === "function") {
      onStatus({ status, error });
    }
  }

  function record(operation, status, startedAt, error = null) {
    if (typeof window === "undefined" || typeof window.WFD_recordSyncMetric !== "function") {
      return;
    }
    window.WFD_recordSyncMetric({
      operation,
      status,
      generation,
      startedAt: startedAt.wall,
      durationMs: performance.now() - startedAt.monotonic,
      error: error ? String(error) : null,
    });
  }

  function refresh(load, apply) {
    if (refreshInFlight) {
      return refreshInFlight;
    }

    const requestedGeneration = generation;
    const startedAt = { monotonic: performance.now(), wall: Date.now() };
    report("loading");
    refreshInFlight = Promise.resolve()
      .then(() => load())
      .then((payload) => {
        if (requestedGeneration < generation) {
          return payload;
        }
        return Promise.resolve(apply(payload, { generation: requestedGeneration })).then(() => {
          report("idle");
          record("refresh", "success", startedAt);
          return payload;
        });
      })
      .catch((error) => {
        report("error", error);
        record("refresh", "error", startedAt, error);
        throw error;
      })
      .finally(() => {
        refreshInFlight = null;
      });
    return refreshInFlight;
  }

  function runPush(request) {
    const pushGeneration = ++generation;
    const startedAt = { monotonic: performance.now(), wall: Date.now() };
    pushStartedAt = startedAt;
    pushKey = request.key;
    report("pushing");
    return Promise.resolve()
      .then(() => request.load())
      .then((payload) => Promise.resolve(request.apply(payload, { generation: pushGeneration })).then(() => payload))
      .then((payload) => {
        if (queuedPushes.length > 0) {
          const next = queuedPushes.shift();
          return runPush(next);
        }
        report("idle");
        record("push", "success", startedAt);
        return payload;
      });
  }

  function push(key, load, apply) {
    if (pushInFlight) {
      if (key !== pushKey) {
        queuedPushes.push({ key, load, apply });
      }
      return pushInFlight;
    }

    pushInFlight = runPush({ key, load, apply })
      .catch((error) => {
        queuedPushes.length = 0;
        report("error", error);
        record("push", "error", pushStartedAt, error);
        throw error;
      })
      .finally(() => {
        pushInFlight = null;
        pushKey = null;
        pushStartedAt = null;
      });
    return pushInFlight;
  }

  function invalidate() {
    generation += 1;
  }

  return {
    refresh,
    push,
    invalidate,
    getGeneration: () => generation,
  };
}