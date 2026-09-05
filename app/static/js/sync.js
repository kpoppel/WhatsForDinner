import { api, isOnline, setApiReachable, browserOnline } from "./api.js";
import { state, persistCache, applyPendingChanges, queueStatusChange, queueDeleteChange, compactPendingChanges, SHOPPING_STATUSES } from "./state.js";
import { render, updateStatusBadges } from "./render.js";

const DEBUG_MODE = false;
let pendingSync = Promise.resolve();

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

function notifySyncFailure() {
  window.alert("Shopping list sync failed. Retry the change or reload the list to revert it.");
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
  if (state.pendingChanges.length > 0) {
    await syncPending(false);
  }
}

function hydrateFromServer(payload) {
  const sections = payload.data.sections;
  const merged = {};
  for (const status of ["remaining", "skipped", "completed"]) {
    for (const item of sections[status]) {
      merged[item.id] = item;
    }
  }
  state.itemsById = merged;
  state.serverCursor = payload.cursor;
  applyPendingChanges();
  persistCache();
}

export async function refresh() {
  const payload = await api("/shopping-list/view");
  hydrateFromServer(payload);
  render();
  show(payload);
  return payload;
}

export function syncPending(showPayload = true) {
  const nextSync = pendingSync.then(() => syncPendingNow(showPayload));
  pendingSync = nextSync.catch(() => {});
  return nextSync.catch((error) => {
    notifySyncFailure();
    throw error;
  });
}

async function syncPendingNow(showPayload) {
  compactPendingChanges();
  persistCache();
  updateStatusBadges();
  if (state.pendingChanges.length === 0) {
    return { source: "local-cache", applied: [], rejected: [] };
  }
  if (!isOnline()) {
    return {
      source: "local-cache",
      message: "Offline. Pending changes are kept locally.",
      pending_count: state.pendingChanges.length,
    };
  }
  const outgoing = [...state.pendingChanges];
  const payload = await api("/shopping-list/sync", {
    method: "POST",
    body: JSON.stringify({ changes: outgoing }),
  });
  const rejectedIndexes = new Set(
    (Array.isArray(payload.rejected) ? payload.rejected : [])
      .map((row) => row.index)
      .filter((value) => Number.isInteger(value) && value >= 0),
  );
  const rejectedChanges = outgoing.filter((_, idx) => rejectedIndexes.has(idx));
  state.pendingChanges = state.pendingChanges.filter((change) => !outgoing.includes(change));
  state.pendingChanges.push(...rejectedChanges);
  if (rejectedChanges.length > 0) {
    notifySyncFailure();
  }
  if (Number.isInteger(payload.server_cursor)) {
    state.serverCursor = payload.server_cursor;
  }
  persistCache();
  try {
    await refresh();
  } catch {
    render();
  }
  if (showPayload) {
    show(payload);
  }
  publishDataChanged();
  return payload;
}

export async function setStatus(entryId, status) {
  if (!SHOPPING_STATUSES.has(status)) {
    throw new Error("Invalid status for shopping mode.");
  }
  queueStatusChange(entryId, status);
  render();
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
    pending_count: state.pendingChanges.length,
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
    queueStatusChange(entryId, status);
  }

  render();
  publishDataChanged();

  if (!isOnline()) {
    show({
      source: "local-cache",
      message: "Offline mode: changes saved locally and queued for sync.",
      entry_ids: ids,
      status,
      pending_count: state.pendingChanges.length,
    });
    return;
  }

  await syncPending(false);
  show({
    source: "shopping-mode",
    message: "Batch status update synced to server.",
    entry_ids: ids,
    status,
    pending_count: state.pendingChanges.length,
  });
}

export async function deleteEntry(entryId) {
  queueDeleteChange(entryId);
  render();
  publishDataChanged();
  if (!isOnline()) {
    show({
      source: "local-cache",
      message: "Offline mode: delete saved locally and queued for sync.",
      entry_id: entryId,
      pending_count: state.pendingChanges.length,
    });
    return;
  }
  await syncPending(false);
  show({
    source: "shopping-mode",
    message: "Delete synced to server.",
    entry_id: entryId,
    pending_count: state.pendingChanges.length,
  });
}

export async function deleteEntries(entryIds) {
  const ids = normalizeEntryIds(entryIds);
  if (ids.length === 0) {
    return;
  }

  for (const entryId of ids) {
    queueDeleteChange(entryId);
  }

  render();
  publishDataChanged();

  if (!isOnline()) {
    show({
      source: "local-cache",
      message: "Offline mode: deletes saved locally and queued for sync.",
      entry_ids: ids,
      pending_count: state.pendingChanges.length,
    });
    return;
  }

  await syncPending(false);
  show({
    source: "shopping-mode",
    message: "Batch delete synced to server.",
    entry_ids: ids,
    pending_count: state.pendingChanges.length,
  });
}
