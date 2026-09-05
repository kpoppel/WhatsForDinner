/**
 * Shopping Mode projection from store selectors to DOM.
 * Rendering is revision/generation aware and contains no backend access.
 */
import {
  toggleShoppingSection,
} from "./store/commands.js";
import {
  selectShoppingApiReachable,
  selectShoppingCollapsedSections,
  selectShoppingItems,
  selectShoppingPendingChanges,
  selectShoppingRejectedChanges,
  selectSyncState,
} from "./store/selectors.js";
import { escapeAttr } from "./utils.js";
import { createRenderScheduler } from "./render_scheduler.js";

const DEBUG_MODE = false;

const SECTION_CONFIG = {
  remaining: {
    titleId: "shop-mode-remaining-title",
    label: "Remaining by Category",
    collapsible: false,
  },
  skipped: {
    titleId: "shop-mode-skipped-title",
    containerId: "shop-mode-skipped",
    label: "Postponed / Skipped",
    collapsible: true,
  },
  completed: {
    titleId: "shop-mode-completed-title",
    containerId: "shop-mode-completed",
    label: "Completed",
    collapsible: true,
  },
};

// Set by initRender() to break the render ↔ gestures circular dependency.
let _createCard;
let latestRenderGeneration = -1;
let latestRenderRevision = -1;
let lastRenderMeta = null;
const renderScheduler = createRenderScheduler({
  render: (options) => renderNow(options),
  getRevision: () => selectSyncState().revision,
});

/** Format numeric quantities without exposing floating-point noise in the UI. */
function formatAmount(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return String(value ?? "").trim();
  }
  const rounded = Math.round((numeric + Number.EPSILON) * 1000) / 1000;
  if (Number.isInteger(rounded)) {
    return String(rounded);
  }
  return String(rounded)
    .replace(/\.0+$/, "")
    .replace(/(\.\d*?)0+$/, "$1");
}

/** Combine an amount and unit while preserving non-numeric source text. */
function amountLine(amount, unit) {
  const amountText = formatAmount(amount);
  const unitText = String(unit || "").trim();
  if (!amountText) {
    return unitText;
  }
  return unitText ? `${amountText} ${unitText}` : amountText;
}

/**
 * Merge rows for the same food while keeping separate unit totals.
 * The returned rows retain all source entry IDs so mutations can address every
 * underlying shopping entry represented by one visible card.
 */
function aggregateByFood(items) {
  const groups = new Map();

  for (const item of items) {
    const foodId = Number.isInteger(item.food_id) ? item.food_id : null;
    const key = foodId !== null ? `food:${foodId}` : `entry:${item.id}`;
    let bucket = groups.get(key);
    if (!bucket) {
      bucket = {
        sample: item,
        entryIds: [],
        units: new Map(),
        fallbackLines: [],
      };
      groups.set(key, bucket);
    }

    if (Number.isInteger(item.id)) {
      bucket.entryIds.push(item.id);
    }

    const unitLabel = String(item.unit || "").trim();
    const unitKey = unitLabel.toLowerCase();
    const numericAmount = Number(item.amount);
    if (Number.isFinite(numericAmount)) {
      const current = bucket.units.get(unitKey) || { amount: 0, unit: unitLabel };
      current.amount += numericAmount;
      if (!current.unit && unitLabel) {
        current.unit = unitLabel;
      }
      bucket.units.set(unitKey, current);
    } else {
      const line = amountLine(item.amount, unitLabel);
      if (line) {
        bucket.fallbackLines.push(line);
      }
    }
  }

  const merged = [];
  for (const bucket of groups.values()) {
    const sample = bucket.sample;
    const unitLines = Array.from(bucket.units.values())
      .sort((a, b) => String(a.unit || "").localeCompare(String(b.unit || "")))
      .map((row) => amountLine(row.amount, row.unit));

    const amountLines = unitLines.length > 0
      ? unitLines
      : (bucket.fallbackLines.length > 0
        ? bucket.fallbackLines
        : [amountLine(sample.amount, sample.unit)].filter(Boolean));

    const [firstLine = ""] = amountLines;
    const entryIds = bucket.entryIds.length > 0
      ? bucket.entryIds
      : (Number.isInteger(sample.id) ? [sample.id] : []);

    merged.push({
      ...sample,
      amount_lines: amountLines,
      amount: firstLine,
      entry_ids: entryIds,
      food_id: Number.isInteger(sample.food_id) ? sample.food_id : null,
    });
  }

  return merged.sort((a, b) => String(a.name).localeCompare(String(b.name)));
}

/** Register the card factory used by this renderer to avoid a module cycle. */
export function initRender(createCardFn) {
  _createCard = createCardFn;
}

/** Update network, pending-change, and reconciliation indicators in the shell. */
export function updateStatusBadges() {
  const network = document.getElementById("shop-mode-network");
  const pending = document.getElementById("shop-mode-pending");
  const pendingCount = document.getElementById("shop-mode-pending-count");
  const syncState = selectSyncState();
  const projectionCount = Array.isArray(syncState.pendingProjections)
    ? syncState.pendingProjections.length
    : 0;
  const pendingChanges = selectShoppingPendingChanges().length;
  const rejectedChanges = selectShoppingRejectedChanges().length;
  const online = selectShoppingApiReachable() && navigator.onLine !== false;

  network.classList.toggle("is-online", online);
  network.classList.toggle("is-offline", !online);
  network.setAttribute("aria-label", online ? "Online" : "Offline");
  network.setAttribute("title", online ? "Online" : "Offline");

  if (pendingCount) {
    pendingCount.textContent = String(pendingChanges + rejectedChanges);
  } else {
    pending.textContent = `o ${pendingChanges + rejectedChanges}`;
  }
  const pendingLabel = `Pending sync: ${pendingChanges}, rejected: ${rejectedChanges}`;
  const projectionLabel = projectionCount > 0 ? `, reconciliation: ${projectionCount}` : "";
  pending.dataset.hasPending = String(pendingChanges + rejectedChanges + projectionCount > 0);
  pending.hidden = pending.dataset.shoppingModeActive !== "true" || pending.dataset.hasPending !== "true";
  pending.disabled = projectionCount === 0;
  pending.setAttribute("aria-label", `${pendingLabel}${projectionLabel}`);
  pending.setAttribute(
    "title",
    projectionCount > 0
      ? `${pendingLabel}${projectionLabel}. Retry reconciliation.`
      : `${pendingLabel}. Correct rejected items to submit a new change.`,
  );
}

/** Return shopping rows for a status in stable alphabetical display order. */
export function sortedByStatus(status) {
  return selectShoppingItems()
    .filter((item) => item && item.status === status)
    .sort((a, b) => String(a.name).localeCompare(String(b.name)));
}

/** Mark a card so a gesture-generated click is ignored once. */
export function suppressNextCardClick(card) {
  card.dataset.suppressNextClick = "1";
}

/** Consume and clear a previously suppressed card click marker. */
export function consumeSuppressedCardClick(card) {
  if (card.dataset.suppressNextClick === "1") {
    card.dataset.suppressNextClick = "0";
    return true;
  }
  return false;
}

/** Build an accessible section heading with its current item count. */
export function titleWithCount(label, count, collapsed) {
  if (typeof collapsed === "boolean") {
    return `${label} (${count}) ${collapsed ? "▸" : "▾"}`;
  }
  return `${label} (${count})`;
}

/** Render a section heading from its configured DOM target and store state. */
export function updateSectionTitle(key, count) {
  const config = SECTION_CONFIG[key];
  if (!config) {
    return;
  }
  const title = document.getElementById(config.titleId);
  if (!title) {
    return;
  }
  if (config.collapsible) {
    const collapsed = !!selectShoppingCollapsedSections()[key];
    title.textContent = titleWithCount(config.label, count, collapsed);
    title.setAttribute("aria-expanded", String(!collapsed));
  } else {
    title.textContent = titleWithCount(config.label, count);
  }
}

/** Apply the persisted collapsed state to one collapsible shopping section. */
export function applyCollapsedSectionState(key) {
  const config = SECTION_CONFIG[key];
  if (!config || !config.collapsible) {
    return;
  }
  const container = document.getElementById(config.containerId);
  if (!container) {
    return;
  }
  container.hidden = !!selectShoppingCollapsedSections()[key];
}

/** Toggle a collapsible section and immediately update its local presentation. */
export function toggleCollapsedSection(key) {
  const config = SECTION_CONFIG[key];
  if (!config || !config.collapsible) {
    return;
  }
  toggleShoppingSection(key);
  applyCollapsedSectionState(key);
  updateSectionTitle(key, sortedByStatus(key).length);
}

/** Install mouse and keyboard handlers for a configured collapsible section. */
export function wireCollapsibleSection(key) {
  const config = SECTION_CONFIG[key];
  if (!config || !config.collapsible) {
    return;
  }
  const title = document.getElementById(config.titleId);
  if (!title) {
    return;
  }
  title.addEventListener("click", () => {
    toggleCollapsedSection(key);
  });
  title.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      toggleCollapsedSection(key);
    }
  });
  applyCollapsedSectionState(key);
}

/** Replace one section's DOM contents with sorted, optionally grouped cards. */
export function renderSection(containerId, items, mode, groupByCategory = false) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  const mergedItems = aggregateByFood(items);
  if (mergedItems.length === 0) {
    container.innerHTML = '<div class="empty">No items.</div>';
    return 0;
  }
  if (!groupByCategory) {
    for (const item of mergedItems) {
      container.appendChild(_createCard(item, mode));
    }
    return mergedItems.length;
  }
  const grouped = {};
  for (const item of mergedItems) {
    const groupName = item.store_group.name;
    if (!grouped[groupName]) {
      grouped[groupName] = [];
    }
    grouped[groupName].push(item);
  }
  const categories = Object.keys(grouped).sort((a, b) => a.localeCompare(b));
  for (const categoryName of categories) {
    const group = document.createElement("section");
    group.className = "category";
    const titleEl = document.createElement("div");
    titleEl.className = "category-title";
    titleEl.textContent = categoryName;
    group.appendChild(titleEl);
    grouped[categoryName]
      .sort((a, b) => a.name.localeCompare(b.name))
      .forEach((item) => group.appendChild(_createCard(item, mode)));
    container.appendChild(group);
  }
  return mergedItems.length;
}

/**
 * Perform a revision-aware DOM render.
 * Older generations and revisions are ignored so delayed work cannot overwrite
 * a newer server response or optimistic state.
 */
function renderNow(options = {}) {
  const renderStartedAt = performance.now();
  const syncState = selectSyncState();
  const generation = Number.isInteger(options.generation)
    ? options.generation
    : latestRenderGeneration;
  const revision = Number.isInteger(options.revision)
    ? options.revision
    : syncState.revision;
  if (generation < latestRenderGeneration || revision < latestRenderRevision) {
    return false;
  }
  latestRenderGeneration = generation;
  latestRenderRevision = revision;
  lastRenderMeta = {
    source: String(options.source || "unknown"),
    status: String(options.status || syncState.status || "idle"),
    revision,
    generation,
    requestedAt: Number.isFinite(options.requestedAt) ? options.requestedAt : null,
    renderedAt: Date.now(),
  };
  if (document.body) {
    document.body.dataset.wfdRenderSource = lastRenderMeta.source;
    document.body.dataset.wfdRenderStatus = lastRenderMeta.status;
  }
  const output = document.getElementById("output");
  if (output) {
    output.style.display = DEBUG_MODE ? "block" : "none";
  }
  const remaining = sortedByStatus("remaining");
  const skipped = sortedByStatus("skipped");
  const completed = sortedByStatus("completed");

  const remainingCount = renderSection("shop-mode-remaining", remaining, "remaining", true);
  const skippedCount = renderSection("shop-mode-skipped", skipped, "skipped");
  const completedCount = renderSection("shop-mode-completed", completed, "completed");

  updateSectionTitle("remaining", remainingCount);
  updateSectionTitle("skipped", skippedCount);
  updateSectionTitle("completed", completedCount);

  updateStatusBadges();
  lastRenderMeta.completedAt = Date.now();
  lastRenderMeta.durationMs = performance.now() - renderStartedAt;
  lastRenderMeta.queueDurationMs = Number.isFinite(options.requestedPerformanceAt)
    ? renderStartedAt - options.requestedPerformanceAt
    : null;
  if (typeof window !== "undefined" && typeof window.WFD_recordRenderMetric === "function") {
    window.WFD_recordRenderMetric({ ...lastRenderMeta });
  }
  return true;
}

/** Return timing and source metadata from the most recent completed render. */
export function getLastRenderMeta() {
  return lastRenderMeta;
}

/** Render immediately, primarily for callers that already own scheduling. */
export function render(options = {}) {
  return renderNow(options);
}

/** Queue a render through the scheduler so bursts collapse into one frame. */
export function requestRender(options = {}) {
  return renderScheduler.request(options);
}

/** Return the number of renders performed by the scheduler. */
export function getRenderCount() {
  return renderScheduler.getRenderCount();
}

export { escapeAttr };
