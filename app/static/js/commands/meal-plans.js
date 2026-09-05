import { api } from "../api.js";

export async function requestMealPlan(path, options) {
  return await api(path, options);
}