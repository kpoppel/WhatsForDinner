import { toggleShoppingSectionCollapsed } from "./commands/shopping-ui.js";
import {
  pendingShoppingChangeCount,
  shoppingApiReachable,
  shoppingItemsByStatus,
  shoppingSectionCollapsed,
} from "./selectors/shopping.js";
import { syncing } from "./selectors/connectivity.js";
import { escapeAttr } from "./utils.js";

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

function amountLine(amount, unit) {
  const amountText = formatAmount(amount);
  const unitText = String(unit || "").trim();
  if (!amountText) {
    return unitText;
  }
  return unitText ? `${amountText} ${unitText}` : amountText;
}

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

export function initRender(createCardFn) {
  _createCard = createCardFn;
}

export function updateStatusBadges() {
  const network = document.getElementById("shop-mode-network");
  const networkDot = network && typeof network.querySelector === "function"
    ? network.querySelector(".status-dot")
    : null;
  const pending = document.getElementById("shop-mode-pending");
  const pendingCount = document.getElementById("shop-mode-pending-count");
  const pendingChangeCount = pendingShoppingChangeCount();
  const online = shoppingApiReachable() && navigator.onLine !== false;

  if (network && networkDot) {
    networkDot.classList.toggle("is-online", online);
    networkDot.classList.toggle("is-offline", !online);
    if (!syncing()) {
      network.setAttribute("aria-label", online ? "Online" : "Offline");
      network.setAttribute("title", online ? "Online" : "Offline");
      const networkLabel = document.getElementById("shop-mode-network-label");
      if (networkLabel) {
        networkLabel.textContent = online ? "Online" : "Offline";
      }
    }
  }

  if (pendingCount) {
    pendingCount.textContent = String(pendingChangeCount);
  } else {
    pending.textContent = `o ${pendingChangeCount}`;
  }
  pending.setAttribute("aria-label", `Pending sync: ${pendingChangeCount}`);
  pending.setAttribute("title", `Pending sync: ${pendingChangeCount}`);
}

export function sortedByStatus(status) {
  return shoppingItemsByStatus(status);
}

export function suppressNextCardClick(card) {
  card.dataset.suppressNextClick = "1";
}

export function consumeSuppressedCardClick(card) {
  if (card.dataset.suppressNextClick === "1") {
    card.dataset.suppressNextClick = "0";
    return true;
  }
  return false;
}

export function titleWithCount(label, count, collapsed) {
  if (typeof collapsed === "boolean") {
    return `${label} (${count}) ${collapsed ? "▸" : "▾"}`;
  }
  return `${label} (${count})`;
}

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
    const collapsed = shoppingSectionCollapsed(key);
    title.textContent = titleWithCount(config.label, count, collapsed);
    title.setAttribute("aria-expanded", String(!collapsed));
  } else {
    title.textContent = titleWithCount(config.label, count);
  }
}

export function applyCollapsedSectionState(key) {
  const config = SECTION_CONFIG[key];
  if (!config || !config.collapsible) {
    return;
  }
  const container = document.getElementById(config.containerId);
  if (!container) {
    return;
  }
  container.hidden = shoppingSectionCollapsed(key);
}

export function toggleCollapsedSection(key) {
  const config = SECTION_CONFIG[key];
  if (!config || !config.collapsible) {
    return;
  }
  toggleShoppingSectionCollapsed(key);
  applyCollapsedSectionState(key);
  updateSectionTitle(key, sortedByStatus(key).length);
}

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

export function render() {
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
}

export { escapeAttr };
