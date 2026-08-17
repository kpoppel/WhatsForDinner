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
      const patch = change.payload;
      if (!patch || typeof patch !== "object") {
        continue;
      }
      const row = state.itemsById[String(id)];
      if (row) {
        Object.assign(row, patch);
        const status = patch.status;
        if (!SHOPPING_STATUSES.has(status)) {
          row.status = row.status || "remaining";
        }
      }
      continue;
    }
    if (change.operation === "create") {
      const payload = change.payload;
      if (!payload || typeof payload !== "object") {
        continue;
      }
      const tempId = shoppingItemId(payload.id);
      if (tempId === null) {
        continue;
      }
      state.itemsById[String(tempId)] = {
        id: tempId,
        food_id: Number.isInteger(payload.food_id) ? payload.food_id : null,
        name: String(payload.name || "Unnamed"),
        amount: payload.amount ?? 0,
        unit: String(payload.unit || ""),
        status: SHOPPING_STATUSES.has(payload.status) ? payload.status : "remaining",
        ingredient_type: String(payload.ingredient_type || "Other"),
        store_group: payload.store_group && typeof payload.store_group === "object"
          ? payload.store_group
          : { id: null, name: "General" },
        recipe: payload.recipe && typeof payload.recipe === "object"
          ? payload.recipe
          : { id: null, name: String(payload.recipe_context || "Unassigned"), image: "" },
        recipe_context: String(payload.recipe_context || "Unassigned"),
        reminder_enabled: Boolean(payload.reminder_enabled),
        reminder_date: payload.reminder_date || null,
        reminder_text: String(payload.reminder_text || ""),
        reminder_due: false,
        raw: { id: tempId, source: "local" },
      };
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
  queueUpdateChange(id, { status });
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

export function queueUpdateChange(entryId, patch) {
  const id = shoppingItemId(entryId);
  if (id === null || !patch || typeof patch !== "object") {
    return;
  }
  state.pendingChanges = state.pendingChanges.filter(
    (change) => shoppingItemId(change.entry_id) !== id,
  );
  state.pendingChanges.push({
    operation: "update",
    entry_id: id,
    payload: patch,
    queued_at: new Date().toISOString(),
  });
  const row = state.itemsById[String(id)];
  if (row) {
    Object.assign(row, patch);
  }
  persistCache();
}

export function queueCreateChange(payload) {
  if (!payload || typeof payload !== "object") {
    return;
  }
  state.pendingChanges.push({
    operation: "create",
    payload,
    queued_at: new Date().toISOString(),
  });
  applyPendingChanges();
  persistCache();
}
