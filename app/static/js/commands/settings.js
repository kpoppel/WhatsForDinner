import { api } from "../api.js";

export async function loadSettingsData() {
  const userSettings = await api("/config/user-settings");
  const mealPlanRules = await api("/config/meal-plan-rules");
  const keywords = await api("/config/keywords");
  const selectedKeywords = await api("/config/keywords/selected");
  return { userSettings, mealPlanRules, keywords, selectedKeywords };
}

export async function saveSettingsData({
  defaultDiners,
  defaultReminderTime,
  noRepeatDays,
  keywordIds,
}) {
  await api("/config/user-settings", {
    method: "PUT",
    body: JSON.stringify({
      default_diners: defaultDiners,
      default_notification_time: defaultReminderTime,
    }),
  });
  await api("/config/meal-plan-rules", {
    method: "PUT",
    body: JSON.stringify({ no_repeat_days: noRepeatDays }),
  });
  await api("/config/keywords/selected", {
    method: "PUT",
    body: JSON.stringify({ keyword_ids: keywordIds }),
  });
}