export const MEAL_PLAN_CACHE_KEY = "wfd.meal-plans.cache.v1";
export const HOME_ACTIVE_PLAN_CACHE_KEY = "wfd.home.active-plan.v1";
export const ACTIVE_MEAL_PLAN_ID_KEY = "wfd.active-meal-plan-id.v1";

export function emptyMealPlanCache() {
  return { list: [], byId: {} };
}
