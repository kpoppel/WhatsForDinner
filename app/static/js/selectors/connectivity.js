import { state } from "../state.js";

export function browserOnline() {
  return navigator.onLine !== false;
}

export function isOnline() {
  return browserOnline() && state.apiReachable;
}

export function apiReachable() {
  return state.apiReachable;
}

export function syncing() {
  return state.syncing;
}