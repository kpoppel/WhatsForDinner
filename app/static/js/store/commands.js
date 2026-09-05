import {
  setActiveMealPlanId,
  setHomeActivePlan,
  setMealPlanCache,
} from "./meal-plan-model.js";
import { readMealPlanCache } from "./selectors.js";

export function writeActiveMealPlanId(planId) {
  setActiveMealPlanId(planId);
}

export function writeMealPlanCache(nextCache) {
  setMealPlanCache(nextCache);
}

export function cachePlanListRows(plans) {
  const current = readMealPlanCache();
  writeMealPlanCache({
    list: plans instanceof Array ? plans : [],
    byId: current.byId,
    updatedAt: new Date().toISOString(),
  });
}

export function cachePlanDetail(plan) {
  const planId = Number(plan && plan.plan_id);
  if (!Number.isInteger(planId)) {
    return;
  }

  const current = readMealPlanCache();
  const byId = {
    ...current.byId,
    [String(planId)]: plan,
  };

  writeMealPlanCache({
    list: current.list,
    byId,
    updatedAt: new Date().toISOString(),
  });
}

export function writeHomeActivePlanCache(plan) {
  if (!plan || typeof plan !== "object") {
    return;
  }
  setHomeActivePlan(plan);
}
