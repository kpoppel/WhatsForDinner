/** Read-only accessors for client model state and persisted cache hydration. */
import {
  ACTIVE_MEAL_PLAN_ID_KEY,
  HOME_ACTIVE_PLAN_CACHE_KEY,
  MEAL_PLAN_CACHE_KEY,
  emptyMealPlanCache,
} from "./schema.js";
import { store } from "./index.js";

/** Return current shopping rows as a stable array snapshot. */
export function selectShoppingItems() {
  return Object.values(store.shopping.itemsById);
}

/** Read one shopping row by normalized ID. */
export function selectShoppingItemById(entryId) {
  return store.shopping.itemsById[String(entryId)];
}

/** Return queued optimistic shopping mutations. */
export function selectShoppingPendingChanges() {
  return store.shopping.pendingChanges;
}

/** Return mutations rejected by the server and awaiting correction. */
export function selectShoppingRejectedChanges() {
  return store.shopping.rejectedChanges;
}

/** Read source/status metadata for a store domain. */
export function selectDomainMeta(domain) {
  if (domain === "shopping") {
    return store.shopping.meta;
  }
  if (domain === "meal-plans") {
    return store.mealPlans.meta;
  }
  if (domain === "settings") {
    return store.settings.meta;
  }
  return store.sync.meta;
}

/** Report the latest API reachability signal used by mutation gating. */
export function selectShoppingApiReachable() {
  return store.shopping.apiReachable;
}

/** Return the persisted collapsed-state map for shopping sections. */
export function selectShoppingCollapsedSections() {
  return store.shopping.collapsedSections;
}

/** Return the cached meal-plan list/detail model. */
export function selectMealPlanCache() {
  return store.mealPlans.cache;
}

/** Return cached meal-plan summaries for list views. */
export function selectMealPlans() {
  return store.mealPlans;
}

/** Return the settings slice used by the settings view. */
export function selectSettings() {
  return store.settings;
}

/** Return browser and API connectivity state. */
export function selectConnectivity() {
  return store.connectivity;
}

/** Return revision, status, and pending projection state. */
export function selectSyncState() {
  return store.sync;
}

/** Return unresolved server-side projection operations. */
export function selectPendingProjections() {
  return store.sync.pendingProjections;
}

/** Read the active meal-plan ID from the in-memory store. */
export function readActiveMealPlanId() {
  if (Number.isInteger(store.mealPlans.activePlanId)) {
    return store.mealPlans.activePlanId;
  }
  try {
    const raw = localStorage.getItem(ACTIVE_MEAL_PLAN_ID_KEY);
    const value = Number(raw);
    if (Number.isInteger(value)) {
      store.mealPlans.activePlanId = value;
      return value;
    }
    return null;
  } catch {
    return null;
  }
}

/** Read the complete meal-plan cache without mutating it. */
export function readMealPlanCache() {
  if (store.mealPlans.cache.list.length > 0 || Object.keys(store.mealPlans.cache.byId).length > 0) {
    return store.mealPlans.cache;
  }
  try {
    const raw = localStorage.getItem(MEAL_PLAN_CACHE_KEY);
    if (!raw) {
      return emptyMealPlanCache();
    }
    const parsed = JSON.parse(raw);
    const base = emptyMealPlanCache();

    if (parsed && typeof parsed === "object") {
      if (parsed.list instanceof Array) {
        base.list = parsed.list;
      }
      if (parsed.byId && typeof parsed.byId === "object") {
        base.byId = parsed.byId;
      }
    }

    store.mealPlans.cache = base;
    return base;
  } catch {
    return emptyMealPlanCache();
  }
}

/** Read the home plan cache, optionally sorting its entry projection. */
export function readHomeActivePlanCache(sortEntries) {
  try {
    const raw = localStorage.getItem(HOME_ACTIVE_PLAN_CACHE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") {
      return null;
    }
    const plan = parsed.plan;
    if (!plan || typeof plan !== "object") {
      return null;
    }

    return {
      plan,
      entries: sortEntries(plan.entries),
    };
  } catch {
    return null;
  }
}
