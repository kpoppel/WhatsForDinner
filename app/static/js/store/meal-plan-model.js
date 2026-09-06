export const MEAL_PLAN_CACHE_KEY = "wfd.meal-plans.cache.v1";
export const HOME_ACTIVE_PLAN_CACHE_KEY = "wfd.home.active-plan.v1";
export const ACTIVE_MEAL_PLAN_ID_KEY = "wfd.active-meal-plan-id.v1";

export function emptyMealPlanCache() {
  return { list: [], byId: {} };
}

function loadActiveMealPlanId() {
  const raw = localStorage.getItem(ACTIVE_MEAL_PLAN_ID_KEY);
  return raw === null ? null : Number(raw);
}

function loadMealPlanCache() {
  const raw = localStorage.getItem(MEAL_PLAN_CACHE_KEY);
  return raw === null ? emptyMealPlanCache() : JSON.parse(raw);
}

function loadHomeActivePlan() {
  const raw = localStorage.getItem(HOME_ACTIVE_PLAN_CACHE_KEY);
  return raw === null ? null : JSON.parse(raw).plan;
}

export const store = {
  mealPlanCache: loadMealPlanCache(),
  activeMealPlanId: loadActiveMealPlanId(),
  homeActivePlan: loadHomeActivePlan(),
};

export function setActiveMealPlanId(planId) {
  store.activeMealPlanId = planId;
  if (planId === null) {
    localStorage.removeItem(ACTIVE_MEAL_PLAN_ID_KEY);
    return;
  }
  localStorage.setItem(ACTIVE_MEAL_PLAN_ID_KEY, String(planId));
}

export function setMealPlanCache(nextCache) {
  store.mealPlanCache = nextCache;
  localStorage.setItem(MEAL_PLAN_CACHE_KEY, JSON.stringify(store.mealPlanCache));
}

export function setHomeActivePlan(plan) {
  store.homeActivePlan = plan;
  localStorage.setItem(HOME_ACTIVE_PLAN_CACHE_KEY, JSON.stringify({
    plan: store.homeActivePlan,
    updatedAt: new Date().toISOString(),
  }));
}