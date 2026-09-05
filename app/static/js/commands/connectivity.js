import { setShoppingApiReachable, state } from "../state.js";
import { health } from "../api.js";

export function setApiReachable(value) {
  setShoppingApiReachable(value);
  if (typeof window.WFD_reportApiReachable === "function") {
    window.WFD_reportApiReachable(state.apiReachable);
  }
}

export async function probeApiReachability() {
  try {
    await health();
    return true;
  } catch {
    return false;
  }
}