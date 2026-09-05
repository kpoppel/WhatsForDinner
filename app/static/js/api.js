/**
 * Sole browser HTTP transport and domain gateway.
 * It normalizes errors, records optional metrics, and publishes API reachability;
 * screen modules call named commands instead of constructing API requests.
 */
import { updateApiReachability } from "./store/index.js";
import { selectShoppingApiReachable } from "./store/selectors.js";
import { updateStatusBadges } from "./render.js";

const apiPrefix = window.WFD_API_PREFIX;
let requestSequence = 0;

function recordRequestMetric(path, operation, requestId, startedAt, wallStartedAt, response, responseSize, requestSize, error = null) {
  if (typeof window.WFD_recordApiMetric !== "function") {
    return;
  }
  window.WFD_recordApiMetric({
    path,
    requestId,
    operation,
    startedAt: wallStartedAt,
    completedAt: Date.now(),
    durationMs: performance.now() - startedAt,
    status: response ? response.status : null,
    correlationId: response && response.headers && typeof response.headers.get === "function"
      ? response.headers.get("X-Correlation-ID")
      : null,
    serverDurationMs: response && response.headers && typeof response.headers.get === "function"
      ? Number(response.headers.get("X-Request-Duration-Ms")) || null
      : null,
    requestSize,
    responseSize,
    error: error ? String(error) : null,
  });
}

function apiError(response, data) {
  const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data);
  const error = new Error(detail);
  error.status = response.status;
  error.detail = data.detail;
  error.data = data;
  return error;
}

export function browserOnline() {
  return navigator.onLine !== false;
}

export function isOnline() {
  return browserOnline() && selectShoppingApiReachable();
}

export function setApiReachable(value) {
  updateApiReachability(value);
  if (typeof window.WFD_reportApiReachable === "function") {
    window.WFD_reportApiReachable(selectShoppingApiReachable());
  }
  if (typeof document !== "undefined") {
    updateStatusBadges();
  }
}

export async function api(path, options = {}, operation = path) {
  return request(path, options, false, operation);
}

async function request(path, options, isUpload, operation) {
  if (options === null) {
    options = {};
  }
  const requestId = `api-${++requestSequence}`;
  const startedAt = performance.now();
  const wallStartedAt = Date.now();
  const requestSize = typeof options.body === "string"
    ? new TextEncoder().encode(options.body).length
    : null;
  let response = null;
  try {
    response = await fetch(`${apiPrefix}${path}`, {
      ...(isUpload ? {} : { headers: { "Content-Type": "application/json" } }),
      ...options,
    });
    const data = await response.json();
    const contentLength = response.headers && typeof response.headers.get === "function"
      ? response.headers.get("content-length")
      : null;
    const responseSize = contentLength === null
      ? new TextEncoder().encode(JSON.stringify(data)).length
      : contentLength;
    if (!response.ok) {
      throw apiError(response, data);
    }
    recordRequestMetric(path, operation, requestId, startedAt, wallStartedAt, response, responseSize, requestSize);
    setApiReachable(true);
    return data;
  } catch (error) {
    recordRequestMetric(path, operation, requestId, startedAt, wallStartedAt, response, null, requestSize, error);
    setApiReachable(response !== null);
    throw error;
  }
}

export async function apiUpload(path, formData) {
  return request(path, { method: "POST", body: formData }, true, `upload:${path}`);
}

export function health() {
  return api("/health", { cache: "no-store" }, "health");
}

export const gateway = {
  health,
  recipes: {
    search(query, limit) {
      return api(`/recipes?search=${encodeURIComponent(query)}&limit=${limit}`, {}, "recipes.search");
    },
  },
  mealPlans: {
    list() {
      return api("/meal-plans/stored", {}, "mealPlans.list");
    },
    get(planId) {
      return api(`/meal-plans/${planId}`, {}, "mealPlans.get");
    },
    generate(payload) {
      return api("/meal-plans/generate", { method: "POST", body: JSON.stringify(payload) }, "mealPlans.generate");
    },
    patch(planId, payload) {
      return api(`/meal-plans/${planId}`, { method: "PATCH", body: JSON.stringify(payload) }, "mealPlans.patch");
    },
    remove(planId) {
      return api(`/meal-plans/stored/${planId}`, { method: "DELETE" }, "mealPlans.remove");
    },
    addEntry(planId, payload) {
      return api(`/meal-plans/${planId}/entries`, { method: "POST", body: JSON.stringify(payload) }, "mealPlans.addEntry");
    },
    patchEntry(planId, entryId, payload) {
      return api(`/meal-plans/${planId}/entries/${entryId}`, { method: "PATCH", body: JSON.stringify(payload) }, "mealPlans.patchEntry");
    },
    deleteEntry(planId, entryId) {
      return api(`/meal-plans/${planId}/entries/${entryId}`, { method: "DELETE" }, "mealPlans.deleteEntry");
    },
    generateShoppingList(planId, mode) {
      return api(`/meal-plans/${planId}/shopping-list?mode=${encodeURIComponent(mode)}`, { method: "POST" }, "mealPlans.generateShoppingList");
    },
  },
  shopping: {
    view(limit = null) {
      const path = Number.isInteger(limit) ? `/shopping-list/view?limit=${limit}` : "/shopping-list/view";
      return api(path, {}, "shopping.view");
    },
    sync(changes) {
      return api("/shopping-list/sync", {
        method: "POST",
        body: JSON.stringify({ changes }),
      }, "shopping.sync");
    },
  },
  settings: {
    user() {
      return api("/config/user-settings", {}, "settings.user");
    },
    rules() {
      return api("/config/meal-plan-rules", {}, "settings.rules");
    },
    keywords() {
      return api("/config/keywords", {}, "settings.keywords");
    },
    selectedKeywords() {
      return api("/config/keywords/selected", {}, "settings.selectedKeywords");
    },
    updateUser(payload) {
      return api("/config/user-settings", { method: "PUT", body: JSON.stringify(payload) }, "settings.updateUser");
    },
    updateRules(payload) {
      return api("/config/meal-plan-rules", { method: "PUT", body: JSON.stringify(payload) }, "settings.updateRules");
    },
    updateSelectedKeywords(keywordIds) {
      return api("/config/keywords/selected", {
        method: "PUT",
        body: JSON.stringify({ keyword_ids: keywordIds }),
      }, "settings.updateSelectedKeywords");
    },
  },
  synchronization: {
    retry(operationId) {
      return api(`/sync/pending/${encodeURIComponent(operationId)}/retry`, { method: "POST" }, "synchronization.retry");
    },
  },
  ocr(formData) {
    return apiUpload("/shopping-list/ocr", formData);
  },
};
