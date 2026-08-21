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

export function queuedEntryId(change) {
  if (!change || typeof change !== "object") {
    return null;
  }
  if (change.operation === "create") {
    return shoppingItemId(change.payload?.id);
  }
  return shoppingItemId(change.entry_id);
}

function mergeCreatePayload(basePayload, patch) {
  const base = basePayload && typeof basePayload === "object" ? basePayload : {};
  const delta = patch && typeof patch === "object" ? patch : {};
  return {
    ...base,
    ...delta,
  };
}

export function compactPendingChanges() {
  const order = [];
  const mergedByKey = new Map();

  for (const change of state.pendingChanges) {
    if (!change || typeof change !== "object") {
      continue;
    }

    const operation = String(change.operation || "").toLowerCase();
    if (!["create", "update", "delete"].includes(operation)) {
      continue;
    }

    const entryId = queuedEntryId(change);
    const key = entryId === null ? `opaque:${order.length}` : `entry:${entryId}`;
    if (!mergedByKey.has(key)) {
      order.push(key);
    }

    const previous = mergedByKey.get(key) || null;
    const next = {
      operation,
      entry_id: entryId,
      payload: change.payload && typeof change.payload === "object" ? { ...change.payload } : undefined,
      queued_at: change.queued_at || new Date().toISOString(),
    };

    if (!previous) {
      mergedByKey.set(key, next);
      continue;
    }

    if (previous.operation === "create") {
      if (operation === "update") {
        previous.payload = mergeCreatePayload(previous.payload, next.payload);
        previous.queued_at = next.queued_at;
        mergedByKey.set(key, previous);
        continue;
      }
      if (operation === "delete") {
        mergedByKey.set(key, null);
        continue;
      }
      if (operation === "create") {
        previous.payload = mergeCreatePayload(previous.payload, next.payload);
        previous.queued_at = next.queued_at;
        mergedByKey.set(key, previous);
        continue;
      }
    }

    if (operation === "update" && previous.operation === "update") {
      previous.payload = mergeCreatePayload(previous.payload, next.payload);
      previous.queued_at = next.queued_at;
      mergedByKey.set(key, previous);
      continue;
    }

    if (operation === "update" && previous.operation === "delete") {
      mergedByKey.set(key, next);
      continue;
    }

    if (operation === "delete") {
      mergedByKey.set(key, {
        operation: "delete",
        entry_id: entryId,
        queued_at: next.queued_at,
      });
      continue;
    }

    mergedByKey.set(key, next);
  }

  const compacted = [];
  for (const key of order) {
    const row = mergedByKey.get(key);
    if (!row) {
      continue;
    }

    if (row.operation === "create") {
      if (row.entry_id === null) {
        continue;
      }
      compacted.push({
        operation: "create",
        entry_id: row.entry_id,
        payload: row.payload || {},
        queued_at: row.queued_at,
      });
      continue;
    }

    if (row.operation === "update") {
      if (row.entry_id === null) {
        continue;
      }
      compacted.push({
        operation: "update",
        entry_id: row.entry_id,
        payload: row.payload || {},
        queued_at: row.queued_at,
      });
      continue;
    }

    if (row.operation === "delete") {
      if (row.entry_id === null) {
        continue;
      }
      compacted.push({
        operation: "delete",
        entry_id: row.entry_id,
        queued_at: row.queued_at,
      });
    }
  }

  state.pendingChanges = compacted;
}

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
    if (change.operation === "delete") {
      const id = shoppingItemId(change.entry_id);
      if (id === null) {
        continue;
      }
      delete state.itemsById[String(id)];
      continue;
    }
    if (change.operation === "update") {
      const id = shoppingItemId(change.entry_id);
      if (id === null) {
        continue;
      }
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
      const tempId = shoppingItemId(payload.id) ?? shoppingItemId(change.entry_id);
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
  compactPendingChanges();
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
    (change) => queuedEntryId(change) !== id,
  );
  state.pendingChanges.push({
    operation: "delete",
    entry_id: id,
    queued_at: new Date().toISOString(),
  });
  compactPendingChanges();
  delete state.itemsById[String(id)];
  persistCache();
}

export function queueUpdateChange(entryId, patch) {
  const id = shoppingItemId(entryId);
  if (id === null || !patch || typeof patch !== "object") {
    return;
  }
  state.pendingChanges = state.pendingChanges.filter(
    (change) => queuedEntryId(change) !== id,
  );
  state.pendingChanges.push({
    operation: "update",
    entry_id: id,
    payload: patch,
    queued_at: new Date().toISOString(),
  });
  compactPendingChanges();
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
  const tempId = shoppingItemId(payload.id);
  if (tempId !== null) {
    state.pendingChanges = state.pendingChanges.filter(
      (change) => queuedEntryId(change) !== tempId,
    );
  }
  state.pendingChanges.push({
    operation: "create",
    entry_id: tempId,
    payload,
    queued_at: new Date().toISOString(),
  });
  compactPendingChanges();
  applyPendingChanges();
  persistCache();
}
