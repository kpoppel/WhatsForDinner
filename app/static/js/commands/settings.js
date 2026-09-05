import { api } from "../api.js";
import { setApiReachable } from "./connectivity.js";

async function executeSettingsRequest(request) {
  try {
    const payload = await request();
    setApiReachable(true);
    return payload;
  } catch (error) {
    setApiReachable(false);
    throw error;
  }
}

export async function loadSettingsData() {
  const userSettings = await executeSettingsRequest(() => api("/config/user-settings"));
  const mealPlanRules = await executeSettingsRequest(() => api("/config/meal-plan-rules"));
  const keywords = await executeSettingsRequest(() => api("/config/keywords"));
  const selectedKeywords = await executeSettingsRequest(() => api("/config/keywords/selected"));
  return { userSettings, mealPlanRules, keywords, selectedKeywords };
}

export async function saveSettingsData({
  defaultDiners,
  defaultReminderTime,
  noRepeatDays,
  keywordIds,
}) {
  await executeSettingsRequest(() => api("/config/settings", {
    method: "PUT",
    body: JSON.stringify({
      default_diners: defaultDiners,
      default_notification_time: defaultReminderTime,
      no_repeat_days: noRepeatDays,
      keyword_ids: keywordIds,
    }),
  }));
}