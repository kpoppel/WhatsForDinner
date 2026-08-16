import { state } from "./state.js";
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

export function initRender(createCardFn) {
  _createCard = createCardFn;
}

export function updateStatusBadges() {
  const network = document.getElementById("shop-mode-network");
  const pending = document.getElementById("shop-mode-pending");
  const pendingCount = document.getElementById("shop-mode-pending-count");
  const online = state.apiReachable && navigator.onLine !== false;

  network.classList.toggle("is-online", online);
  network.classList.toggle("is-offline", !online);
  network.setAttribute("aria-label", online ? "Online" : "Offline");
  network.setAttribute("title", online ? "Online" : "Offline");

  if (pendingCount) {
    pendingCount.textContent = String(state.pendingChanges.length);
  } else {
    pending.textContent = `o ${state.pendingChanges.length}`;
  }
  pending.setAttribute("aria-label", `Pending sync: ${state.pendingChanges.length}`);
  pending.setAttribute("title", `Pending sync: ${state.pendingChanges.length}`);
}

export function sortedByStatus(status) {
  return Object.values(state.itemsById)
    .filter((item) => item && item.status === status)
    .sort((a, b) => String(a.name).localeCompare(String(b.name)));
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
    const collapsed = !!state.collapsedSections[key];
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
  container.hidden = !!state.collapsedSections[key];
}

export function toggleCollapsedSection(key) {
  const config = SECTION_CONFIG[key];
  if (!config || !config.collapsible) {
    return;
  }
  state.collapsedSections[key] = !state.collapsedSections[key];
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
  if (items.length === 0) {
    container.innerHTML = '<div class="empty">No items.</div>';
    return;
  }
  if (!groupByCategory) {
    for (const item of items) {
      container.appendChild(_createCard(item, mode));
    }
    return;
  }
  const grouped = {};
  for (const item of items) {
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
}

export function render() {
  const output = document.getElementById("output");
  if (output) {
    output.style.display = DEBUG_MODE ? "block" : "none";
  }
  const remaining = sortedByStatus("remaining");
  const skipped = sortedByStatus("skipped");
  const completed = sortedByStatus("completed");

  renderSection("shop-mode-remaining", remaining, "remaining", true);
  renderSection("shop-mode-skipped", skipped, "skipped");
  renderSection("shop-mode-completed", completed, "completed");

  updateSectionTitle("remaining", remaining.length);
  updateSectionTitle("skipped", skipped.length);
  updateSectionTitle("completed", completed.length);

  updateStatusBadges();
}

export { escapeAttr };
