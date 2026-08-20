import { emptyMealPlanCache } from "./schema.js";

export const store = {
  mealPlanCache: emptyMealPlanCache(),
  activeMealPlanId: null,
  homeActivePlan: null,
};
