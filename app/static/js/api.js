import { setShoppingApiReachable, state } from "./state.js";

const apiPrefix = window.WFD_API_PREFIX;

function publishApiReachability(value) {
  const previous = state.apiReachable;
  setShoppingApiReachable(value);
  if (previous !== Boolean(value)) {
    window.dispatchEvent(new CustomEvent("wfd:api-reachability-changed"));
  }
}

export async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(`${apiPrefix}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (error) {
    publishApiReachability(false);
    throw error;
  }
  publishApiReachability(true);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || JSON.stringify(data));
  }
  return data;
}

export async function apiUpload(path, formData) {
  let response;
  try {
    response = await fetch(`${apiPrefix}${path}`, {
      method: "POST",
      body: formData,
    });
  } catch (error) {
    publishApiReachability(false);
    throw error;
  }
  publishApiReachability(true);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || JSON.stringify(data));
  }
  return data;
}

export async function health() {
  return await api("/health", { cache: "no-store", signal: AbortSignal.timeout(5000) });
}
