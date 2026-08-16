import { state } from "./state.js";
import { updateStatusBadges } from "./render.js";

const apiPrefix = window.WFD_API_PREFIX;

export function browserOnline() {
  return navigator.onLine !== false;
}

export function isOnline() {
  return browserOnline() && state.apiReachable;
}

export function setApiReachable(value) {
  state.apiReachable = Boolean(value);
  updateStatusBadges();
}

export async function api(path, options = {}) {
  try {
    const response = await fetch(`${apiPrefix}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(JSON.stringify(data));
    }
    setApiReachable(true);
    return data;
  } catch (error) {
    setApiReachable(false);
    throw error;
  }
}
