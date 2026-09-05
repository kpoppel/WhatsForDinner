/** Read-only accessors for client model state and persisted cache hydration. */
import {
  ACTIVE_MEAL_PLAN_ID_KEY,
  HOME_ACTIVE_PLAN_CACHE_KEY,
  MEAL_PLAN_CACHE_KEY,
  emptyMealPlanCache,
} from "./schema.js";
import { store } from "./index.js";

export function selectShoppingItems() {
  return Object.values(store.shopping.itemsById);
}

export function selectShoppingItemById(entryId) {
  return store.shopping.itemsById[String(entryId)];
}

export function selectShoppingPendingChanges() {
  return store.shopping.pendingChanges;
}

export function selectShoppingRejectedChanges() {
  return store.shopping.rejectedChanges;
}

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

export function selectShoppingApiReachable() {
  return store.shopping.apiReachable;
}

export function selectShoppingCollapsedSections() {
  return store.shopping.collapsedSections;
}

export function selectMealPlanCache() {
  return store.mealPlans.cache;
}

export function selectMealPlans() {
  return store.mealPlans;
}

export function selectSettings() {
  return store.settings;
}

export function selectConnectivity() {
  return store.connectivity;
}

export function selectSyncState() {
  return store.sync;
}

export function selectPendingProjections() {
  return store.sync.pendingProjections;
}

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
