import { api } from "../api.js";
import { setApiReachable } from "./connectivity.js";

async function executeHomeRequest(request) {
  try {
    const payload = await request();
    setApiReachable(true);
    return payload;
  } catch (error) {
    setApiReachable(false);
    throw error;
  }
}

export async function searchHomeRecipes(query) {
  return await executeHomeRequest(() => api(`/recipes?search=${encodeURIComponent(query)}&limit=20`));
}

export async function loadStoredMealPlans() {
  return await executeHomeRequest(() => api("/meal-plans/stored"));
}

export async function loadMealPlan(planId) {
  return await executeHomeRequest(() => api(`/meal-plans/${planId}`));
}

export async function loadShoppingList(limit) {
  return await executeHomeRequest(() => api(`/shopping-list/view?limit=${limit}`));
}