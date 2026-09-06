import { api } from "../api.js";

export async function loadStoredMealPlans() {
  return await api("/meal-plans/stored");
}

export async function loadMealPlan(planId) {
  return await api(`/meal-plans/${planId}`);
}

export async function updateMealPlanEntry(planId, entryId, patch) {
  return await api(`/meal-plans/${planId}/entries/${entryId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function deleteMealPlanEntry(planId, entryId) {
  return await api(`/meal-plans/${planId}/entries/${entryId}`, {
    method: "DELETE",
  });
}

export async function deleteStoredMealPlan(planId) {
  return await api(`/meal-plans/stored/${planId}`, {
    method: "DELETE",
  });
}

export async function createMealPlanEntry(planId, entry) {
  return await api(`/meal-plans/${planId}/entries`, {
    method: "POST",
    body: JSON.stringify(entry),
  });
}

export async function generateMealPlanShoppingList(planId, mode) {
  return await api(
    `/meal-plans/${planId}/shopping-list?mode=${encodeURIComponent(mode)}`,
    { method: "POST" },
  );
}

export async function loadMealPlanDefaultDiners() {
  return await api("/config/user-settings");
}

export async function updateMealPlanStartDate(planId, startDate) {
  return await api(`/meal-plans/${planId}`, {
    method: "PATCH",
    body: JSON.stringify({ start_date: startDate }),
  });
}

export async function generateMealPlan(plan) {
  return await api("/meal-plans/generate", {
    method: "POST",
    body: JSON.stringify(plan),
  });
}

export async function searchMealPlanRecipes(query) {
  return await api(`/recipes?search=${encodeURIComponent(query)}&limit=8`);
}