import { api } from "../api.js";

async function executeMealPlanRequest(request, reportApiReachable) {
  try {
    const payload = await request();
    reportApiReachable(true);
    return payload;
  } catch (error) {
    reportApiReachable(false);
    throw error;
  }
}

export async function loadStoredMealPlans(reportApiReachable) {
  return await executeMealPlanRequest(() => api("/meal-plans/stored"), reportApiReachable);
}

export async function loadMealPlan(planId, reportApiReachable) {
  return await executeMealPlanRequest(() => api(`/meal-plans/${planId}`), reportApiReachable);
}

export async function updateMealPlanEntry(planId, entryId, patch, reportApiReachable) {
  return await executeMealPlanRequest(() => api(`/meal-plans/${planId}/entries/${entryId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  }), reportApiReachable);
}

export async function deleteMealPlanEntry(planId, entryId, reportApiReachable) {
  return await executeMealPlanRequest(() => api(`/meal-plans/${planId}/entries/${entryId}`, {
    method: "DELETE",
  }), reportApiReachable);
}

export async function deleteStoredMealPlan(planId, reportApiReachable) {
  return await executeMealPlanRequest(() => api(`/meal-plans/stored/${planId}`, {
    method: "DELETE",
  }), reportApiReachable);
}

export async function createMealPlanEntry(planId, entry, reportApiReachable) {
  return await executeMealPlanRequest(() => api(`/meal-plans/${planId}/entries`, {
    method: "POST",
    body: JSON.stringify(entry),
  }), reportApiReachable);
}

export async function generateMealPlanShoppingList(planId, mode, reportApiReachable) {
  return await executeMealPlanRequest(() => api(
    `/meal-plans/${planId}/shopping-list?mode=${encodeURIComponent(mode)}`,
    { method: "POST" },
  ), reportApiReachable);
}

export async function loadMealPlanDefaultDiners(reportApiReachable) {
  return await executeMealPlanRequest(() => api("/config/user-settings"), reportApiReachable);
}

export async function updateMealPlanStartDate(planId, startDate, reportApiReachable) {
  return await executeMealPlanRequest(() => api(`/meal-plans/${planId}`, {
    method: "PATCH",
    body: JSON.stringify({ start_date: startDate }),
  }), reportApiReachable);
}

export async function generateMealPlan(plan, reportApiReachable) {
  return await executeMealPlanRequest(() => api("/meal-plans/generate", {
    method: "POST",
    body: JSON.stringify(plan),
  }), reportApiReachable);
}

export async function searchMealPlanRecipes(query, reportApiReachable) {
  return await executeMealPlanRequest(() => api(
    `/recipes?search=${encodeURIComponent(query)}&limit=8`,
  ), reportApiReachable);
}