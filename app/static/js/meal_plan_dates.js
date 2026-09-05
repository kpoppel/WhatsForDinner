/** Return the local calendar date represented by an ISO date string. */
function parseIsoDate(text) {
  if (typeof text !== "string") {
    return null;
  }

  const parsed = new Date(`${text}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/** Return whether a meal plan has any date remaining from today onward. */
export function isMealPlanActive(plan, nowDate = new Date()) {
  const startDate = parseIsoDate(plan && plan.start_date);
  const lengthDays = Number(plan && plan.length_days);
  if (startDate === null || !Number.isInteger(lengthDays) || lengthDays < 1) {
    return false;
  }

  const today = new Date(nowDate.getFullYear(), nowDate.getMonth(), nowDate.getDate());
  startDate.setDate(startDate.getDate() + lengthDays - 1);
  return startDate.getTime() >= today.getTime();
}

/** Select the first active plan while preserving the caller's plan ordering. */
export function selectActiveMealPlan(plans, nowDate = new Date()) {
  if (!(plans instanceof Array)) {
    return null;
  }
  const activePlan = plans.find((plan) => isMealPlanActive(plan, nowDate));
  return activePlan === undefined ? null : activePlan;
}