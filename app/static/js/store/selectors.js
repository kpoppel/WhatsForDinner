import { store } from "./meal-plan-model.js";

export function readActiveMealPlanId() {
  return store.activeMealPlanId;
}

// A plan covering today takes precedence over the last opened or upcoming plan.
export function selectActiveMealPlan(rows, preferredId, today) {
  let currentPlan = null;
  for (const row of rows) {
    const start = row.start_date;
    const length = Number(row.length_days);
    if (typeof start !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(start)
        || !Number.isInteger(length) || length < 1) {
      continue;
    }
    const end = new Date(`${start}T00:00:00`);
    end.setDate(end.getDate() + length - 1);
    const endDate = `${end.getFullYear()}-${String(end.getMonth() + 1).padStart(2, "0")}-${String(end.getDate()).padStart(2, "0")}`;
    if (start <= today && today <= endDate && (currentPlan === null || start > currentPlan.start_date)) {
      currentPlan = row;
    }
  }
  if (currentPlan !== null) {
    return currentPlan;
  }
  const preferredRow = rows.find((row) => Number(row.plan_id) === preferredId);
  if (preferredRow) {
    return preferredRow;
  }
  return rows[0];
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
