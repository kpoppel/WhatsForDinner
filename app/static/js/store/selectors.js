import { store } from "./meal-plan-model.js";

export function readActiveMealPlanId() {
  return store.activeMealPlanId;
}

export function readMealPlanCache() {
  return structuredClone(store.mealPlanCache);
}

export function readHomeActivePlanCache(sortEntries) {
  const plan = structuredClone(store.homeActivePlan);
  if (!plan) {
    return null;
  }

  return {
    plan,
    entries: sortEntries(plan.entries),
  };
}
