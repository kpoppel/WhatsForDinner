export const MEAL_PLAN_CACHE_KEY = "wfd.meal-plans.cache.v1";
export const HOME_ACTIVE_PLAN_CACHE_KEY = "wfd.home.active-plan.v1";
export const ACTIVE_MEAL_PLAN_ID_KEY = "wfd.active-meal-plan-id.v1";

export function emptyMealPlanCache() {
  return { list: [], byId: {} };
}

function loadActiveMealPlanId() {
  try {
    const raw = localStorage.getItem(ACTIVE_MEAL_PLAN_ID_KEY);
    const value = Number(raw);
    if (Number.isInteger(value)) {
      return value;
    }
  } catch {
    // Ignore localStorage failures.
  }
  return null;
}

function loadMealPlanCache() {
  const base = emptyMealPlanCache();
  try {
    const raw = localStorage.getItem(MEAL_PLAN_CACHE_KEY);
    if (!raw) {
      return base;
    }
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") {
      if (parsed.list instanceof Array) {
        base.list = parsed.list;
      }
      if (parsed.byId && typeof parsed.byId === "object") {
        base.byId = parsed.byId;
      }
    }
  } catch {
    // Ignore localStorage failures.
  }
  return base;
}

function loadHomeActivePlan() {
  try {
    const raw = localStorage.getItem(HOME_ACTIVE_PLAN_CACHE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && parsed.plan && typeof parsed.plan === "object") {
      return parsed.plan;
    }
  } catch {
    // Ignore localStorage failures.
  }
  return null;
}

export const store = {
  mealPlanCache: loadMealPlanCache(),
  activeMealPlanId: loadActiveMealPlanId(),
  homeActivePlan: loadHomeActivePlan(),
};

export function setActiveMealPlanId(planId) {
  store.activeMealPlanId = Number.isInteger(planId) ? planId : null;
  try {
    if (store.activeMealPlanId === null) {
      localStorage.removeItem(ACTIVE_MEAL_PLAN_ID_KEY);
      return;
    }
    localStorage.setItem(ACTIVE_MEAL_PLAN_ID_KEY, String(store.activeMealPlanId));
  } catch {
    // Ignore localStorage failures.
  }
}

export function setMealPlanCache(nextCache) {
  store.mealPlanCache = nextCache;
  try {
    localStorage.setItem(MEAL_PLAN_CACHE_KEY, JSON.stringify(store.mealPlanCache));
  } catch {
    // Ignore localStorage failures.
  }
}

export function setHomeActivePlan(plan) {
  store.homeActivePlan = plan;
  try {
    localStorage.setItem(HOME_ACTIVE_PLAN_CACHE_KEY, JSON.stringify({
      plan: store.homeActivePlan,
      updatedAt: new Date().toISOString(),
    }));
  } catch {
    // Ignore localStorage failures.
  }
}