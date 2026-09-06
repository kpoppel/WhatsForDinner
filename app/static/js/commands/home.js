import { api } from "../api.js";

export async function searchHomeRecipes(query) {
  return await api(`/recipes?search=${encodeURIComponent(query)}&limit=20`);
}

export async function loadStoredMealPlans() {
  return await api("/meal-plans/stored");
}

export async function loadMealPlan(planId) {
  return await api(`/meal-plans/${planId}`);
}

export async function loadShoppingList(limit) {
  return await api(`/shopping-list/view?limit=${limit}`);
}