/**
 * Mutable client model and shopping persistence implementation.
 * Only store commands mutate this object; UI modules observe it through
 * selectors and subscription notifications.
 */
import { shoppingItemId } from "../utils.js";
import { emptyMealPlanCache } from "./schema.js";

export const store = {
  mealPlans: {
    meta: { source: "empty", status: "cached", revision: 0, error: null },
    cache: emptyMealPlanCache(),
    activePlanId: null,
    homeActivePlan: null,
    selectedPlanId: null,
    selectedPlan: null,
  },
  settings: {
    meta: { source: "default", status: "cached", revision: 0, error: null },
    user: {
      default_diners: 2,
      default_notification_time: "",
    },
    rules: {
      no_repeat_days: 14,
    },
    keywordCatalog: [],
    selectedKeywordIds: new Set(),
  },
  connectivity: {
    browserOnline: true,
    apiReachable: true,
  },
  sync: {
    meta: { source: "initial", status: "idle", revision: 0, error: null },
    status: "idle",
    lastSource: null,
    lastError: null,
    revision: 0,
    pendingProjections: [],
  },
  shopping: {
    meta: { source: "empty", status: "cached", revision: 0, error: null },
    itemsById: {},
    pendingChanges: [],
    rejectedChanges: [],
    serverCursor: 0,
    apiReachable: true,
    collapsedSections: {
      skipped: true,
      completed: true,
    },
  },
};

const subscribers = new Set();
let crossTabSyncInstalled = false;

export function subscribe(listener) {
  if (typeof listener !== "function") {
    return () => {};
  }
  subscribers.add(listener);
  return () => subscribers.delete(listener);
}

export function installCrossTabSync() {
  if (crossTabSyncInstalled || typeof window === "undefined") {
    return;
  }
  crossTabSyncInstalled = true;
  window.addEventListener("storage", (event) => {
    if (!event || event.key !== "wfd.shopping-mode.v1") {
      return;
    }
    loadShoppingCache();
    notifyStore("shopping", "cross-tab", "server");
  });
}

export function notifyStore(domain, source, status, revision = store.sync.revision) {
  const target = domain === "shopping"
    ? store.shopping
    : domain === "meal-plans"
      ? store.mealPlans
      : domain === "settings"
        ? store.settings
        : store.sync;
  target.meta = { ...target.meta, source, status, revision };
  const notification = { domain, source, status, revision };
  for (const listener of subscribers) {
    listener(notification);
  }
}

export function updateApiReachability(value) {
  const reachable = Boolean(value);
  store.shopping.apiReachable = reachable;
  store.connectivity = { ...store.connectivity, apiReachable: reachable };
  notifyStore("sync", "connectivity", "server");
}

export function toggleShoppingSectionState(section) {
  store.shopping.collapsedSections[section] = !store.shopping.collapsedSections[section];
}

export const SHOPPING_STATUSES = new Set(["remaining", "skipped", "completed"]);

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
  return { ...base, ...delta };
}

export function compactPendingChanges() {
  const shopping = store.shopping;
  const order = [];
  const mergedByKey = new Map();

  for (const change of shopping.pendingChanges) {
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
      mergedByKey.set(key, { operation: "delete", entry_id: entryId, queued_at: next.queued_at });
      continue;
    }
    mergedByKey.set(key, next);
  }

  shopping.pendingChanges = order
    .map((key) => mergedByKey.get(key))
    .filter((row) => row && (row.entry_id !== null || row.operation === "delete"))
    .map((row) => row.operation === "create"
      ? { operation: "create", entry_id: row.entry_id, payload: row.payload || {}, queued_at: row.queued_at }
      : row.operation === "update"
        ? { operation: "update", entry_id: row.entry_id, payload: row.payload || {}, queued_at: row.queued_at }
        : { operation: "delete", entry_id: row.entry_id, queued_at: row.queued_at });
}

function applyShoppingChange(change, applyDelete) {
  const shopping = store.shopping;
  if (!change) {
    return;
  }
  if (change.operation === "delete") {
    if (applyDelete) {
      const id = shoppingItemId(change.entry_id);
      if (id !== null) {
        delete shopping.itemsById[String(id)];
      }
    }
    return;
  }
  if (change.operation === "update") {
    const id = shoppingItemId(change.entry_id);
    const patch = change.payload;
    const row = id === null ? null : shopping.itemsById[String(id)];
    if (row && patch && typeof patch === "object") {
      Object.assign(row, patch);
      if (!SHOPPING_STATUSES.has(patch.status)) {
        row.status = row.status || "remaining";
      }
    }
    return;
  }
  if (change.operation === "create") {
    const payload = change.payload;
    const tempId = payload && typeof payload === "object"
      ? shoppingItemId(payload.id) ?? shoppingItemId(change.entry_id)
      : null;
    if (tempId === null || !payload || typeof payload !== "object") {
      return;
    }
    shopping.itemsById[String(tempId)] = {
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

export function applyPendingChanges() {
  for (const change of store.shopping.pendingChanges) {
    applyShoppingChange(change, true);
  }
  for (const change of store.shopping.rejectedChanges) {
    applyShoppingChange(change, false);
  }
}

export function persistShoppingCache() {
  try {
    localStorage.setItem("wfd.shopping-mode.v1", JSON.stringify({
      ...store.shopping,
      derived_state_revision: store.sync.revision,
      pending_projections: store.sync.pendingProjections,
    }));
  } catch {
    // Ignore write failures.
  }
}

export function loadShoppingCache() {
  try {
    const raw = localStorage.getItem("wfd.shopping-mode.v1");
    if (!raw) {
      return;
    }
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") {
      if (parsed.itemsById && typeof parsed.itemsById === "object") {
        store.shopping.itemsById = parsed.itemsById;
      }
      if (Array.isArray(parsed.pendingChanges)) {
        store.shopping.pendingChanges = parsed.pendingChanges;
      }
      if (Array.isArray(parsed.rejectedChanges)) {
        store.shopping.rejectedChanges = parsed.rejectedChanges;
      }
      if (Number.isInteger(parsed.serverCursor)) {
        store.shopping.serverCursor = parsed.serverCursor;
      }
      if (Number.isInteger(parsed.derived_state_revision)) {
        store.sync.revision = Math.max(store.sync.revision, parsed.derived_state_revision);
      }
      if (parsed.pending_projections instanceof Array) {
        store.sync.pendingProjections = parsed.pending_projections;
      }
    }
  } catch {
    store.shopping.itemsById = {};
    store.shopping.pendingChanges = [];
    store.shopping.serverCursor = 0;
  }
  compactPendingChanges();
  applyPendingChanges();
  persistShoppingCache();
}

export function queueStatusChange(entryId, status) {
  const id = shoppingItemId(entryId);
  if (id !== null && SHOPPING_STATUSES.has(status)) {
    queueUpdateChange(id, { status });
  }
}

export function queueDeleteChange(entryId) {
  const shopping = store.shopping;
  const id = shoppingItemId(entryId);
  if (id === null) {
    return;
  }
  shopping.pendingChanges = shopping.pendingChanges.filter((change) => queuedEntryId(change) !== id);
  shopping.rejectedChanges = shopping.rejectedChanges.filter((change) => queuedEntryId(change) !== id);
  shopping.pendingChanges.push({ operation: "delete", entry_id: id, queued_at: new Date().toISOString() });
  compactPendingChanges();
  delete shopping.itemsById[String(id)];
  persistShoppingCache();
  notifyStore("shopping", "command", "optimistic");
}

export function queueUpdateChange(entryId, patch) {
  const shopping = store.shopping;
  const id = shoppingItemId(entryId);
  if (id === null || !patch || typeof patch !== "object") {
    return;
  }
  shopping.pendingChanges = shopping.pendingChanges.filter((change) => queuedEntryId(change) !== id);
  shopping.rejectedChanges = shopping.rejectedChanges.filter((change) => queuedEntryId(change) !== id);
  shopping.pendingChanges.push({ operation: "update", entry_id: id, payload: patch, queued_at: new Date().toISOString() });
  compactPendingChanges();
  const row = shopping.itemsById[String(id)];
  if (row) {
    Object.assign(row, patch);
  }
  persistShoppingCache();
  notifyStore("shopping", "command", "optimistic");
}

export function queueCreateChange(payload) {
  const shopping = store.shopping;
  if (!payload || typeof payload !== "object") {
    return;
  }
  const tempId = shoppingItemId(payload.id);
  if (tempId !== null) {
    shopping.pendingChanges = shopping.pendingChanges.filter((change) => queuedEntryId(change) !== tempId);
  }
  shopping.pendingChanges.push({ operation: "create", entry_id: tempId, payload, queued_at: new Date().toISOString() });
  compactPendingChanges();
  applyPendingChanges();
  persistShoppingCache();
  notifyStore("shopping", "command", "optimistic");
}
