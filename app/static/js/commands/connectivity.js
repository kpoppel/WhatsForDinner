import { setShoppingApiReachable } from "../state.js";
import { health } from "../api.js";

// Must match HEALTH_SERVICE_ID in app/api.py.
const HEALTH_SERVICE_ID = "whatsfordinner";

export function setApiReachable(value) {
  setShoppingApiReachable(value);
}

/**
 * Probe the API and report whether this specific server answered. The service
 * marker is checked so a JSON-speaking captive portal or an unrelated host on a
 * foreign network cannot be mistaken for the home server.
 */
export async function probeApiReachability() {
  let payload;
  try {
    payload = await health();
  } catch {
    setShoppingApiReachable(false);
    return false;
  }
  const reachable = payload.status === "ok" && payload.service === HEALTH_SERVICE_ID;
  setShoppingApiReachable(reachable);
  return reachable;
}