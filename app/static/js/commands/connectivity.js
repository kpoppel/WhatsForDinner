import { setShoppingApiReachable } from "../state.js";
import { health } from "../api.js";

export function setApiReachable(value) {
  setShoppingApiReachable(value);
}

export async function probeApiReachability() {
  try {
    await health();
    setApiReachable(true);
    return true;
  } catch {
    setApiReachable(false);
    return false;
  }
}