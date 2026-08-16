import { shoppingItemId } from "./utils.js";

export const CACHE_KEY = "wfd.shopping-mode.v1";
export const SHOPPING_STATUSES = new Set(["remaining", "skipped", "completed"]);

export const state = {
  itemsById: {},
  pendingChanges: [],
  serverCursor: 0,
  apiReachable: true,
  collapsedSections: {
    skipped: true,
    completed: true,
  },
};

export function persistCache() {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(state));
  } catch {
    // Ignore write failures.
  }
}

export function applyPendingChanges() {
  for (const change of state.pendingChanges) {
    if (!change) {
      continue;
    }
    const id = shoppingItemId(change.entry_id);
    if (id === null) {
      continue;
    }
    if (change.operation === "delete") {
      delete state.itemsById[String(id)];
      continue;
    }
    if (change.operation === "update") {
      const status = change.payload?.status;
      if (!SHOPPING_STATUSES.has(status)) {
        continue;
      }
      const row = state.itemsById[String(id)];
      if (row) {
        row.status = status;
      }
    }
  }
}

export function loadCache() {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) {
      return;
    }
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") {
      if (parsed.itemsById && typeof parsed.itemsById === "object") {
        state.itemsById = parsed.itemsById;
      }
      if (Array.isArray(parsed.pendingChanges)) {
        state.pendingChanges = parsed.pendingChanges;
      }
      if (Number.isInteger(parsed.serverCursor)) {
        state.serverCursor = parsed.serverCursor;
      }
    }
  } catch {
    state.itemsById = {};
    state.pendingChanges = [];
    state.serverCursor = 0;
  }
  applyPendingChanges();
  persistCache();
}

export function queueStatusChange(entryId, status) {
  const id = shoppingItemId(entryId);
  if (id === null || !SHOPPING_STATUSES.has(status)) {
    return;
  }
  state.pendingChanges = state.pendingChanges.filter(
    (change) => shoppingItemId(change.entry_id) !== id,
  );
  state.pendingChanges.push({
    operation: "update",
    entry_id: id,
    payload: { status },
    queued_at: new Date().toISOString(),
  });
  const row = state.itemsById[String(id)];
  if (row) {
    row.status = status;
  }
  persistCache();
}

export function queueDeleteChange(entryId) {
  const id = shoppingItemId(entryId);
  if (id === null) {
    return;
  }
  state.pendingChanges = state.pendingChanges.filter(
    (change) => shoppingItemId(change.entry_id) !== id,
  );
  state.pendingChanges.push({
    operation: "delete",
    entry_id: id,
    queued_at: new Date().toISOString(),
  });
  delete state.itemsById[String(id)];
  persistCache();
}
