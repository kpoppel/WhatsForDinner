/**
 * Shopping synchronization workflow between optimistic store commands and the
 * backend gateway. All pushes and canonical refreshes pass through the shared
 * coordinator so pending changes survive failures and stale reads are ignored.
 */
import { gateway, isOnline, setApiReachable, browserOnline } from "./api.js";
import {
  applyShoppingSyncResult,
  acceptsRevision,
  compactShoppingPendingChanges,
  deleteShoppingChange,
  hydrateShoppingModel,
  restoreShoppingPendingChanges,
  setShoppingStatus,
  setPendingProjections,
  setRevision,
  setSyncState,
  takeShoppingPendingChanges,
} from "./store/commands.js";
import { SHOPPING_STATUSES } from "./store/index.js";
import { selectPendingProjections, selectShoppingPendingChanges } from "./store/selectors.js";
import { requestRender, updateStatusBadges } from "./render.js";
import { createSyncCoordinator } from "./sync_coordinator.js";

const DEBUG_MODE = false;
const coordinator = createSyncCoordinator({
  onStatus({ status, error }) {
    setSyncState({ status, lastError: error ? String(error) : null, source: "coordinator" });
  },
});

export function show(data) {
  if (!DEBUG_MODE) {
    return;
  }
  const output = document.getElementById("output");
  if (output) {
    output.textContent = JSON.stringify(data, null, 2);
  }
}

function publishDataChanged() {
  window.dispatchEvent(new CustomEvent("wfd:data-changed", { detail: { source: "shopping-mode" } }));
}

function normalizeEntryIds(entryIds) {
  if (!Array.isArray(entryIds)) {
    return [];
  }
  return Array.from(new Set(
    entryIds
      .map((value) => Number(value))
      .filter((value) => Number.isInteger(value) && value !== 0),
  ));
}

export async function run(action) {
  try {
    await action();
  } catch (err) {
    show({ message: "Request failed", status: `Error: ${err}` });
  }
}

export async function refreshAndSyncIfNeeded() {
  if (!browserOnline()) {
    setApiReachable(false);
    updateStatusBadges();
    return;
  }
  await refresh();
  if (selectShoppingPendingChanges().length > 0) {
    await syncPending(false);
  }
}

function hydrateFromServer(payload) {
  hydrateShoppingModel(payload.data.sections, payload.cursor);
}

export async function refresh() {
  return coordinator.refresh(
    () => gateway.shopping.view(),
    (payload, context) => {
      if (!acceptsRevision(payload.revision)) {
        return;
      }
      if (Number.isInteger(payload.revision)) {
        setRevision(payload.revision, "refresh");
      }
      if (Array.isArray(payload.pending_projections)) {
        setPendingProjections(payload.pending_projections, "refresh");
      }
      hydrateFromServer(payload);
      requestRender({
        source: "server",
        status: "server",
        generation: context.generation,
        revision: payload.revision,
      });
      show(payload);
    },
  );
}

export async function syncPending(showPayload = true) {
  compactShoppingPendingChanges();
  updateStatusBadges();
  if (selectShoppingPendingChanges().length === 0) {
    return { source: "local-cache", applied: [], rejected: [] };
  }
  if (!isOnline()) {
    return {
      source: "local-cache",
      message: "Offline. Pending changes are kept locally.",
      pending_count: selectShoppingPendingChanges().length,
    };
  }
  const outgoing = takeShoppingPendingChanges();
  try {
    return await coordinator.push(
      JSON.stringify(outgoing),
      () => gateway.shopping.sync(outgoing),
      async (payload, context) => {
      if (Number.isInteger(payload.revision)) {
        setRevision(payload.revision, "sync");
      }
      if (Array.isArray(payload.pending_projections)) {
        setPendingProjections(payload.pending_projections, "sync");
      }
      if (payload.projection && payload.projection.status === "pending") {
        setPendingProjections([payload.projection], "sync");
      }
      const rejectedIndexes = new Set(
        (Array.isArray(payload.rejected) ? payload.rejected : [])
          .map((row) => row.index)
          .filter((value) => Number.isInteger(value) && value >= 0),
      );
      applyShoppingSyncResult(outgoing, payload.rejected);
      if (payload.data && payload.data.sections) {
        hydrateFromServer(payload);
      }
      requestRender({
        source: "reconciliation",
        status: rejectedIndexes.size > 0 ? "rejected" : "server",
        generation: context.generation,
        revision: payload.revision,
      });
      if (showPayload) {
        show(payload);
      }
      publishDataChanged();
      },
    );
  } catch (error) {
    restoreShoppingPendingChanges(outgoing);
    throw error;
  }
}

export async function retryPendingProjections() {
  const pending = [...selectPendingProjections()];
  for (const projection of pending) {
    const payload = await gateway.synchronization.retry(projection.operation_id);
    if (Number.isInteger(payload.revision)) {
      setRevision(payload.revision, "projection-retry");
    }
    setPendingProjections(payload.pending_projections, "projection-retry");
    if (payload.data && payload.data.sections) {
      hydrateFromServer(payload);
      requestRender({
        source: "reconciliation",
        status: "server",
        revision: payload.revision,
        generation: coordinator.getGeneration(),
      });
    }
  }
  publishDataChanged();
}

export async function setStatus(entryId, status) {
  if (!SHOPPING_STATUSES.has(status)) {
    throw new Error("Invalid status for shopping mode.");
  }
  setShoppingStatus(entryId, status);
  coordinator.invalidate();
  requestRender({ source: "optimistic", status: "optimistic", generation: coordinator.getGeneration(), force: true });
  publishDataChanged();
  if (!isOnline()) {
    show({
      source: "local-cache",
      message: "Offline mode: change saved locally and queued for sync.",
      entry_id: entryId,
      status,
    });
    return;
  }
  await syncPending(false);
  show({
    source: "shopping-mode",
    message: "Status updated and synced to server.",
    entry_id: entryId,
    status,
    pending_count: selectShoppingPendingChanges().length,
  });
}

export async function setStatusMany(entryIds, status) {
  if (!SHOPPING_STATUSES.has(status)) {
    throw new Error("Invalid status for shopping mode.");
  }
  const ids = normalizeEntryIds(entryIds);
  if (ids.length === 0) {
    return;
  }

  for (const entryId of ids) {
    setShoppingStatus(entryId, status);
  }

  coordinator.invalidate();
  requestRender({ source: "optimistic", status: "optimistic", generation: coordinator.getGeneration(), force: true });
  publishDataChanged();

  if (!isOnline()) {
    show({
      source: "local-cache",
      message: "Offline mode: changes saved locally and queued for sync.",
      entry_ids: ids,
      status,
      pending_count: selectShoppingPendingChanges().length,
    });
    return;
  }

  await syncPending(false);
  show({
    source: "shopping-mode",
    message: "Batch status update synced to server.",
    entry_ids: ids,
    status,
    pending_count: selectShoppingPendingChanges().length,
  });
}

export async function deleteEntry(entryId) {
  deleteShoppingChange(entryId);
  coordinator.invalidate();
  requestRender({ source: "optimistic", status: "optimistic", generation: coordinator.getGeneration(), force: true });
  publishDataChanged();
  if (!isOnline()) {
    show({
      source: "local-cache",
      message: "Offline mode: delete saved locally and queued for sync.",
      entry_id: entryId,
      pending_count: selectShoppingPendingChanges().length,
    });
    return;
  }
  await syncPending(false);
  show({
    source: "shopping-mode",
    message: "Delete synced to server.",
    entry_id: entryId,
    pending_count: selectShoppingPendingChanges().length,
  });
}

export async function deleteEntries(entryIds) {
  const ids = normalizeEntryIds(entryIds);
  if (ids.length === 0) {
    return;
  }

  for (const entryId of ids) {
    deleteShoppingChange(entryId);
  }

  coordinator.invalidate();
  requestRender({ source: "optimistic", status: "optimistic", generation: coordinator.getGeneration(), force: true });
  publishDataChanged();

  if (!isOnline()) {
    show({
      source: "local-cache",
      message: "Offline mode: deletes saved locally and queued for sync.",
      entry_ids: ids,
      pending_count: selectShoppingPendingChanges().length,
    });
    return;
  }

  await syncPending(false);
  show({
    source: "shopping-mode",
    message: "Batch delete synced to server.",
    entry_ids: ids,
    pending_count: selectShoppingPendingChanges().length,
  });
}
