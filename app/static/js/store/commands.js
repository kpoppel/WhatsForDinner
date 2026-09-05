/**
 * Public mutation and backend-command boundary for screen modules.
 * Commands own model writes, persistence, revision checks, and delegation to
 * the HTTP gateway; they do not render DOM.
 */
import {
  ACTIVE_MEAL_PLAN_ID_KEY,
  HOME_ACTIVE_PLAN_CACHE_KEY,
  MEAL_PLAN_CACHE_KEY,
} from "./schema.js";
import {
  applyPendingChanges,
  compactPendingChanges,
  loadShoppingCache,
  persistShoppingCache,
  queueCreateChange,
  queueDeleteChange,
  queueStatusChange,
  queueUpdateChange,
  queuedEntryId,
  notifyStore,
  store,
  toggleShoppingSectionState,
} from "./index.js";
import { readMealPlanCache } from "./selectors.js";
import { gateway as gatewayApi } from "../api.js";

export function writeActiveMealPlanId(planId) {
  store.mealPlans.activePlanId = Number.isInteger(planId) ? planId : null;
  try {
    if (!Number.isInteger(planId)) {
      localStorage.removeItem(ACTIVE_MEAL_PLAN_ID_KEY);
      return;
    }
    localStorage.setItem(ACTIVE_MEAL_PLAN_ID_KEY, String(planId));
  } catch {
    // Ignore localStorage failures.
  }
}

export function writeMealPlanCache(nextCache) {
  store.mealPlans.cache = nextCache;
  notifyStore("meal-plans", "cache", "cached");
  try {
    localStorage.setItem(MEAL_PLAN_CACHE_KEY, JSON.stringify(nextCache));
  } catch {
    // Ignore localStorage failures.
  }
}

export function cachePlanListRows(plans) {
  const current = readMealPlanCache();
  writeMealPlanCache({
    list: plans instanceof Array ? plans : [],
    byId: current.byId,
    updatedAt: new Date().toISOString(),
  });
}

export function cachePlanDetail(plan) {
  const planId = Number(plan && plan.plan_id);
  if (!Number.isInteger(planId)) {
    return;
  }

  const current = readMealPlanCache();
  const byId = {
    ...current.byId,
    [String(planId)]: plan,
  };

  writeMealPlanCache({
    list: current.list,
    byId,
    updatedAt: new Date().toISOString(),
  });
}

export function writeHomeActivePlanCache(plan) {
  if (!plan || typeof plan !== "object") {
    return;
  }
  store.mealPlans.homeActivePlan = plan;
  notifyStore("meal-plans", "cache", "cached");
  try {
    localStorage.setItem(HOME_ACTIVE_PLAN_CACHE_KEY, JSON.stringify({
      plan,
      updatedAt: new Date().toISOString(),
    }));
  } catch {
    // Ignore localStorage failures.
  }
}

export function loadShoppingCacheCommand() {
  loadShoppingCache();
}

export function persistShoppingModel() {
  persistShoppingCache();
}

export function applyShoppingPendingChanges() {
  applyPendingChanges();
}

export function compactShoppingPendingChanges() {
  compactPendingChanges();
}

export function createShoppingChange(payload) {
  queueCreateChange(payload);
}

export function updateShoppingChange(entryId, patch) {
  queueUpdateChange(entryId, patch);
}

export function deleteShoppingChange(entryId) {
  queueDeleteChange(entryId);
}

export function setShoppingStatus(entryId, status) {
  queueStatusChange(entryId, status);
}

export function takeShoppingPendingChanges() {
  compactPendingChanges();
  const outgoing = [...store.shopping.pendingChanges];
  store.shopping.pendingChanges = [];
  persistShoppingCache();
  return outgoing;
}

export function restoreShoppingPendingChanges(changes) {
  store.shopping.pendingChanges = [...changes, ...store.shopping.pendingChanges];
  compactPendingChanges();
  applyPendingChanges();
  persistShoppingCache();
}

export function applyShoppingSyncResult(outgoing, rejected) {
  const rejectedRows = rejected instanceof Array ? rejected : [];
  const outgoingIds = new Set(outgoing.map((change) => queuedEntryId(change)));
  store.shopping.rejectedChanges = [
    ...store.shopping.rejectedChanges.filter((change) => !outgoingIds.has(queuedEntryId(change))),
    ...rejectedRows.map((row) => ({ ...outgoing[row.index], error: row })),
  ];
  applyPendingChanges();
  persistShoppingCache();
}

export function hydrateShoppingModel(sections, cursor) {
  const merged = {};
  for (const status of ["remaining", "skipped", "completed"]) {
    for (const item of sections[status]) {
      merged[item.id] = item;
    }
  }
  store.shopping.rejectedChanges = store.shopping.rejectedChanges.filter((change) => {
    if (change.operation === "create") {
      return true;
    }
    const entryId = queuedEntryId(change);
    return entryId !== null && Object.hasOwn(merged, String(entryId));
  });
  store.shopping.itemsById = merged;
  store.shopping.serverCursor = cursor;
  applyPendingChanges();
  persistShoppingCache();
}

export function setConnectivityState(nextState) {
  store.connectivity = { ...store.connectivity, ...nextState };
  notifyStore("sync", "connectivity", "server");
}

export function toggleShoppingSection(section) {
  toggleShoppingSectionState(section);
}

export function setSyncState(nextState) {
  store.sync = { ...store.sync, ...nextState };
  notifyStore("sync", nextState.source || "coordinator", nextState.status || store.sync.status);
}

export function setSettingsSlice(nextSettings) {
  store.settings = { ...store.settings, ...nextSettings };
  notifyStore("settings", "command", "server");
}

export function assertOnlineMutation(domain) {
  const browserOnline = typeof navigator === "undefined" || navigator.onLine !== false;
  if (!browserOnline || !store.shopping.apiReachable) {
    throw new Error(`Cannot mutate ${domain} while offline.`);
  }
}

export function setSettingsUserValue(field, value) {
  store.settings.user = { ...store.settings.user, [field]: value };
  notifyStore("settings", "command", "optimistic");
}

export function setSettingsRuleValue(field, value) {
  store.settings.rules = { ...store.settings.rules, [field]: value };
  notifyStore("settings", "command", "optimistic");
}

export function setKeywordCatalog(rows) {
  store.settings.keywordCatalog = Array.isArray(rows) ? rows : [];
  notifyStore("settings", "command", "server");
}

export function setSelectedKeywordIds(ids) {
  store.settings.selectedKeywordIds = new Set(Array.isArray(ids) ? ids : []);
  notifyStore("settings", "command", "optimistic");
}

export function setMealPlanSelection(planId) {
  store.mealPlans.selectedPlanId = Number.isInteger(planId) ? planId : null;
  notifyStore("meal-plans", "command", "optimistic");
}

export function setMealPlanDetail(plan) {
  store.mealPlans.selectedPlan = plan && typeof plan === "object" ? plan : null;
  notifyStore("meal-plans", "command", "server");
}

export function setRevision(revision, source = "server") {
  if (!Number.isInteger(revision) || revision < store.sync.revision) {
    return false;
  }
  store.sync.revision = revision;
  persistShoppingCache();
  notifyStore("sync", source, "server", store.sync.revision);
  return true;
}

export function acceptsRevision(revision) {
  return !Number.isInteger(revision) || revision >= store.sync.revision;
}

export function setPendingProjections(projections, source = "server") {
  store.sync.pendingProjections = Array.isArray(projections) ? projections : [];
  persistShoppingCache();
  notifyStore("sync", source, "pending", store.sync.revision);
}

export const recipeCommands = {
  search(query, limit) {
    return gatewayApi.recipes.search(query, limit);
  },
};

export const mealPlanCommands = {
  list() {
    return gatewayApi.mealPlans.list();
  },
  get(planId) {
    return gatewayApi.mealPlans.get(planId);
  },
  generate(payload) {
    return gatewayApi.mealPlans.generate(payload);
  },
  patch(planId, payload) {
    return gatewayApi.mealPlans.patch(planId, payload);
  },
  remove(planId) {
    return gatewayApi.mealPlans.remove(planId);
  },
  addEntry(planId, payload) {
    return gatewayApi.mealPlans.addEntry(planId, payload);
  },
  patchEntry(planId, entryId, payload) {
    return gatewayApi.mealPlans.patchEntry(planId, entryId, payload);
  },
  deleteEntry(planId, entryId) {
    return gatewayApi.mealPlans.deleteEntry(planId, entryId);
  },
  generateShoppingList(planId, mode) {
    return gatewayApi.mealPlans.generateShoppingList(planId, mode);
  },
};

export const shoppingCommands = {
  view(limit = null) {
    return gatewayApi.shopping.view(limit);
  },
};

export const settingsCommands = {
  user() {
    return gatewayApi.settings.user();
  },
  rules() {
    return gatewayApi.settings.rules();
  },
  keywords() {
    return gatewayApi.settings.keywords();
  },
  selectedKeywords() {
    return gatewayApi.settings.selectedKeywords();
  },
  updateUser(payload) {
    return gatewayApi.settings.updateUser(payload);
  },
  updateRules(payload) {
    return gatewayApi.settings.updateRules(payload);
  },
  updateSelectedKeywords(keywordIds) {
    return gatewayApi.settings.updateSelectedKeywords(keywordIds);
  },
};

export async function loadSettingsResources() {
  const [user, rules, keywords, selectedKeywords] = await Promise.all([
    settingsCommands.user(),
    settingsCommands.rules(),
    settingsCommands.keywords(),
    settingsCommands.selectedKeywords(),
  ]);
  return { user, rules, keywords, selectedKeywords };
}

export async function saveSettingsResources(user, rules, keywordIds) {
  await settingsCommands.updateUser(user);
  await settingsCommands.updateRules(rules);
  await settingsCommands.updateSelectedKeywords(keywordIds);
}
