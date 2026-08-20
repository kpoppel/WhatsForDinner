import {
  ACTIVE_MEAL_PLAN_ID_KEY,
  HOME_ACTIVE_PLAN_CACHE_KEY,
  MEAL_PLAN_CACHE_KEY,
  emptyMealPlanCache,
} from "./schema.js";

export function readActiveMealPlanId() {
  try {
    const raw = localStorage.getItem(ACTIVE_MEAL_PLAN_ID_KEY);
    const value = Number(raw);
    if (Number.isInteger(value)) {
      return value;
    }
    return null;
  } catch {
    return null;
  }
}

export function readMealPlanCache() {
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
