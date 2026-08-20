import {
  ACTIVE_MEAL_PLAN_ID_KEY,
  HOME_ACTIVE_PLAN_CACHE_KEY,
  MEAL_PLAN_CACHE_KEY,
} from "./schema.js";
import { readMealPlanCache } from "./selectors.js";

const apiPrefix = window.WFD_API_PREFIX;

export function writeActiveMealPlanId(planId) {
  try {
    if (!Number.isInteger(planId)) {
      localStorage.removeItem(ACTIVE_MEAL_PLAN_ID_KEY);
      return;
    }
    localStorage.setItem(ACTIVE_MEAL_PLAN_ID_KEY, String(planId));
  } catch {
    // Ignore localStorage failures.
  }
}

export function writeMealPlanCache(nextCache) {
  try {
    localStorage.setItem(MEAL_PLAN_CACHE_KEY, JSON.stringify(nextCache));
  } catch {
    // Ignore localStorage failures.
  }
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
  try {
    localStorage.setItem(HOME_ACTIVE_PLAN_CACHE_KEY, JSON.stringify({
      plan,
      updatedAt: new Date().toISOString(),
    }));
  } catch {
    // Ignore localStorage failures.
  }
}

export async function api(path, options, reportApiReachable) {
  let opts = {};
  if (options && typeof options === "object") {
    opts = options;
  }

  try {
    const response = await fetch(`${apiPrefix}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });

    const payload = await response.json();
    if (!response.ok) {
      if (typeof payload.detail === "string") {
        throw new Error(payload.detail);
      }
      throw new Error(JSON.stringify(payload));
    }

    if (typeof reportApiReachable === "function") {
      reportApiReachable(true);
    }
    return payload;
  } catch (error) {
    if (typeof reportApiReachable === "function") {
      reportApiReachable(false);
    }
    throw error;
  }
}
