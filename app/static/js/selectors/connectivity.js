import { state } from "../state.js";

export function browserOnline() {
  return navigator.onLine !== false;
}

export function isOnline() {
  return browserOnline() && state.apiReachable;
}