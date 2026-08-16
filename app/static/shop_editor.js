import { state, persistCache, queueCreateChange, queueDeleteChange, queueUpdateChange } from "./js/state.js";
import { refresh, run, syncPending } from "./js/sync.js";
import { isOnline } from "./js/api.js";

const VIEW_KEY = "wfd.shop-editor.view.v1";
const SEGMENT_DEFAULT = "store";
const STEP = 0.5;
const MIN_SYNCED_AMOUNT = 0.1;

const listNode = document.getElementById("wf-editor-list");
const statusNode = document.getElementById("wf-editor-status");
const dueBannerNode = document.getElementById("wf-editor-due-banner");
const addButton = document.getElementById("wf-editor-add-btn");
const segmentButtons = Array.from(document.querySelectorAll("[data-editor-view]"));

const addModal = document.getElementById("wf-editor-add-modal");
const editModal = document.getElementById("wf-editor-edit-modal");

if (!listNode || !statusNode || !dueBannerNode || !addButton || !addModal || !editModal) {
  // Shop Editor UI is not mounted on this page.
} else {
  initShopEditor();
}

function initShopEditor() {
  bindSegmentControls();
  bindToolbarControls();
  bindModalControls();
  bindTabActivation();
  updateDueBanner();
  renderEditor();
}

function setStatus(message) {
  statusNode.textContent = message;
}

function publishDataChanged() {
  window.dispatchEvent(new CustomEvent("wfd:data-changed", { detail: { source: "shop-editor" } }));
}

function activeView() {
  const value = localStorage.getItem(VIEW_KEY);
  return value === "recipe" ? "recipe" : SEGMENT_DEFAULT;
}

function setActiveView(next) {
  localStorage.setItem(VIEW_KEY, next);
  for (const button of segmentButtons) {
    const selected = button.dataset.editorView === next;
    button.classList.toggle("is-active", selected);
    button.setAttribute("aria-selected", String(selected));
  }
  renderEditor();
}

function bindSegmentControls() {
  setActiveView(activeView());
  for (const button of segmentButtons) {
    button.addEventListener("click", () => {
      const next = button.dataset.editorView === "recipe" ? "recipe" : "store";
      setActiveView(next);
    });
  }
}

function bindToolbarControls() {
  addButton.addEventListener("click", () => {
    openAddModal();
  });
}

function serverStoreGroupNames() {
  const categories = new Set(["Other"]);
  for (const item of Object.values(state.itemsById)) {
    if (!item) {
      continue;
    }
    const text = String(item.store_group?.name || "").trim();
    if (text) {
      categories.add(text);
    }
  }
  return Array.from(categories).sort((a, b) => a.localeCompare(b));
}

function populateCategorySelect(selectId, selectedValue) {
  const select = document.getElementById(selectId);
  if (!(select instanceof HTMLSelectElement)) {
    return;
  }
  const categories = serverStoreGroupNames();
  if (selectedValue && !categories.includes(selectedValue)) {
    categories.push(selectedValue);
    categories.sort((a, b) => a.localeCompare(b));
  }
  select.innerHTML = "";
  for (const category of categories) {
    const option = document.createElement("option");
    option.value = category;
    option.textContent = category;
    option.selected = category === selectedValue;
    select.appendChild(option);
  }
}

function bindTabActivation() {
  const shopButton = document.querySelector('.wf-nav-btn[data-tab="shop-editor"]');
  if (shopButton) {
    shopButton.addEventListener("click", () => {
      run(async () => {
        await refresh();
        renderEditor();
      });
    });
  }
}

function bindModalControls() {
  document.getElementById("wf-add-cancel")?.addEventListener("click", closeAddModal);
  document.getElementById("wf-add-save")?.addEventListener("click", () => {
    run(saveAddModal);
  });

  document.getElementById("wf-edit-cancel")?.addEventListener("click", closeEditModal);
  document.getElementById("wf-edit-save")?.addEventListener("click", () => {
    run(saveEditModal);
  });
  document.getElementById("wf-edit-delete")?.addEventListener("click", () => {
    run(deleteFromEditModal);
  });
}

function allItems() {
  return Object.values(state.itemsById)
    .filter((row) => row && row.id !== undefined && row.id !== null)
    .sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
}

function groupKey(item, view) {
  if (view === "recipe") {
    return String(item.recipe_context || "Unassigned");
  }
  const group = item.store_group;
  if (group && typeof group === "object") {
    return String(group.name || "General");
  }
  return "General";
}

function groupedItems() {
  const view = activeView();
  const groups = {};
  for (const item of allItems()) {
    const key = groupKey(item, view);
    if (!groups[key]) {
      groups[key] = [];
    }
    groups[key].push(item);
  }
  return Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0]));
}

function updateDueBanner() {
  const due = allItems().filter((item) => item.reminder_enabled && item.reminder_due);
  if (due.length === 0) {
    dueBannerNode.hidden = true;
    dueBannerNode.textContent = "";
    return;
  }
  dueBannerNode.hidden = false;
  dueBannerNode.textContent = `${due.length} reminder${due.length === 1 ? "" : "s"} due today.`;
}

function renderEditor() {
  listNode.innerHTML = "";
  updateDueBanner();

  const grouped = groupedItems();
  if (grouped.length === 0) {
    listNode.innerHTML = '<article class="wf-editor-empty">No shopping items available yet.</article>';
    return;
  }

  for (const [groupName, items] of grouped) {
    const section = document.createElement("section");
    section.className = "wf-editor-group";

    const heading = document.createElement("h3");
    heading.className = "wf-editor-group-title";
    heading.textContent = `${groupName} (${items.length})`;
    section.appendChild(heading);

    const stack = document.createElement("div");
    stack.className = "wf-editor-group-items";
    for (const item of items) {
      stack.appendChild(createEditorRow(item));
    }
    section.appendChild(stack);
    listNode.appendChild(section);
  }
}

function createEditorRow(item) {
  const row = document.createElement("article");
  row.className = "wf-editor-item";

  const amount = Number(item.amount ?? 0);
  const safeAmount = Number.isFinite(amount) ? amount : 0;
  const unit = String(item.unit || "").trim();
  const status = String(item.status || "remaining");
  const reminderOn = Boolean(item.reminder_enabled);

  row.innerHTML = `
    <div class="wf-editor-main">
      <p class="wf-editor-name">${escapeHtml(item.name || "Unnamed")}</p>
      <p class="wf-editor-meta">${escapeHtml(item.recipe_context || "Unassigned")} • ${escapeHtml(item.ingredient_type || "Other")}</p>
      <p class="wf-editor-meta wf-editor-meta-light">${escapeHtml(status)}</p>
    </div>
    <div class="wf-editor-actions">
      <button class="wf-bell-btn ${reminderOn ? "is-on" : ""}" type="button" data-action="toggle-reminder">🔔</button>
      <div class="wf-stepper" role="group" aria-label="Quantity controls">
        <button class="wf-stepper-btn" type="button" data-action="decrement">-</button>
        <span class="wf-stepper-value">${formatAmount(safeAmount)}${unit ? ` ${escapeHtml(unit)}` : ""}</span>
        <button class="wf-stepper-btn" type="button" data-action="increment">+</button>
      </div>
    </div>
  `;

  row.querySelector('[data-action="increment"]')?.addEventListener("click", () => {
    run(() => adjustAmount(item.id, safeAmount + STEP));
  });

  row.querySelector('[data-action="decrement"]')?.addEventListener("click", () => {
    run(() => adjustAmount(item.id, Math.max(0, safeAmount - STEP)));
  });

  row.querySelector('[data-action="toggle-reminder"]')?.addEventListener("click", () => {
    run(() => toggleReminder(item));
  });

  row.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    if (target.closest(".wf-editor-actions")) {
      return;
    }
    openEditModal(item);
  });

  return row;
}

async function adjustAmount(entryId, nextAmount) {
  const rounded = Math.round(nextAmount * 2) / 2;
  const isLocalAdHoc = Number(entryId) < 0;
  const finalAmount = isLocalAdHoc
    ? Math.max(0, rounded)
    : Math.max(MIN_SYNCED_AMOUNT, rounded);
  await queueAndSyncUpdate(entryId, { amount: finalAmount });
  if (!isLocalAdHoc && finalAmount === MIN_SYNCED_AMOUNT && rounded < MIN_SYNCED_AMOUNT) {
    setStatus("Minimum for synced items is 0.1 to avoid upstream removal.");
  }
  renderEditor();
  publishDataChanged();
}

function deriveReminderDate(item) {
  const candidates = [
    item?.raw?.meal_date,
    item?.raw?.planned_date,
    item?.raw?.date,
    item?.raw?.use_date,
  ];
  for (const value of candidates) {
    if (typeof value !== "string") {
      continue;
    }
    const text = value.trim();
    if (!text) {
      continue;
    }
    const parsed = new Date(text);
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.toISOString().slice(0, 10);
    }
  }
  return null;
}

async function toggleReminder(item) {
  if (!item.reminder_enabled) {
    const derived = deriveReminderDate(item);
    if (!derived) {
      openEditModal({ ...item, reminder_enabled: true });
      setStatus("Set a reminder date in Edit Item.");
      return;
    }
    const text = item.reminder_text && item.reminder_text.trim()
      ? item.reminder_text.trim()
      : `${item.name} thaw/prep reminder`;
    await queueAndSyncUpdate(item.id, {
      reminder_enabled: true,
      reminder_date: derived,
      reminder_text: text,
    });
    setStatus("Reminder enabled.");
    renderEditor();
    publishDataChanged();
    return;
  }

  await queueAndSyncUpdate(item.id, {
    reminder_enabled: false,
    reminder_date: null,
  });
  setStatus("Reminder cleared.");
  renderEditor();
  publishDataChanged();
}

function openAddModal() {
  addModal.hidden = false;
  const categories = serverStoreGroupNames();
  const initialCategory = categories.includes("Other") ? "Other" : (categories[0] || "Other");
  setInputValue("wf-add-name", "");
  setInputValue("wf-add-amount", "0");
  populateCategorySelect("wf-add-category", initialCategory);
  setInputValue("wf-add-reminder-date", "");
  setInputValue("wf-add-reminder-text", "");
  setChecked("wf-add-reminder-enabled", false);
}

function closeAddModal() {
  addModal.hidden = true;
}

async function saveAddModal() {
  const name = getInputValue("wf-add-name").trim();
  if (!name) {
    throw new Error("Item name is required.");
  }

  const amount = toNumber(getInputValue("wf-add-amount"), 0);
  const category = getInputValue("wf-add-category").trim() || "Other";
  const reminderEnabled = getChecked("wf-add-reminder-enabled");
  const reminderDate = getInputValue("wf-add-reminder-date") || null;
  const reminderTextRaw = getInputValue("wf-add-reminder-text").trim();
  const reminderText = reminderTextRaw || `${name} thaw/prep reminder`;

  const tempId = nextTempId();
  const payload = {
    id: tempId,
    ad_hoc: true,
    name,
    amount,
    unit: "",
    ingredient_type: "Other",
    store_group: { id: null, name: category },
    recipe_context: "Unassigned",
    status: "remaining",
    reminder_enabled: reminderEnabled,
    reminder_date: reminderEnabled ? reminderDate : null,
    reminder_text: reminderEnabled ? reminderText : "",
  };

  queueCreateChange(payload);
  renderEditor();

  if (isOnline()) {
    await syncPending(false);
    await refresh();
    renderEditor();
    setStatus("Item added.");
    publishDataChanged();
  } else {
    setStatus("Offline: item queued and will sync when online.");
    publishDataChanged();
  }

  closeAddModal();
}

function openEditModal(item) {
  editModal.hidden = false;
  setInputValue("wf-edit-entry-id", String(item.id));
  setInputValue("wf-edit-name", String(item.name || ""));
  setInputValue("wf-edit-amount", String(item.amount ?? 0));
  populateCategorySelect("wf-edit-category", String(item.store_group?.name || "Other"));
  setChecked("wf-edit-reminder-enabled", Boolean(item.reminder_enabled));
  setInputValue("wf-edit-reminder-date", item.reminder_date || "");
  setInputValue("wf-edit-reminder-text", item.reminder_text || `${item.name} thaw/prep reminder`);
}

function closeEditModal() {
  editModal.hidden = true;
}

async function saveEditModal() {
  const entryId = Number(getInputValue("wf-edit-entry-id"));
  if (!Number.isInteger(entryId) || entryId === 0) {
    throw new Error("Invalid shopping item.");
  }

  const name = getInputValue("wf-edit-name").trim();
  if (!name) {
    throw new Error("Item name is required.");
  }

  const amount = toNumber(getInputValue("wf-edit-amount"), 0);
  const category = getInputValue("wf-edit-category").trim() || "Other";
  const reminderEnabled = getChecked("wf-edit-reminder-enabled");
  const reminderDate = getInputValue("wf-edit-reminder-date") || null;
  const reminderTextRaw = getInputValue("wf-edit-reminder-text").trim();
  const reminderText = reminderTextRaw || `${name} thaw/prep reminder`;

  const patch = {
    name,
    amount,
    reminder_enabled: reminderEnabled,
    reminder_date: reminderEnabled ? reminderDate : null,
    reminder_text: reminderEnabled ? reminderText : "",
  };

  if (entryId < 0) {
    patch.store_group = { id: null, name: category };
  }

  await queueAndSyncUpdate(entryId, patch);

  closeEditModal();
  renderEditor();
  setStatus("Item updated.");
  publishDataChanged();
}

async function deleteFromEditModal() {
  const entryId = Number(getInputValue("wf-edit-entry-id"));
  if (!Number.isInteger(entryId) || entryId === 0) {
    throw new Error("Invalid shopping item.");
  }

  queueDeleteChange(entryId);
  renderEditor();

  if (isOnline()) {
    await syncPending(false);
    await refresh();
  }

  closeEditModal();
  renderEditor();
  setStatus(isOnline() ? "Item deleted." : "Offline: delete queued.");
  publishDataChanged();
}

async function queueAndSyncUpdate(entryId, patch) {
  queueUpdateChange(entryId, patch);
  persistCache();

  if (!isOnline()) {
    setStatus("Offline: change queued and will sync when online.");
    return;
  }

  await syncPending(false);
  await refresh();
}

function nextTempId() {
  const ids = Object.keys(state.itemsById)
    .map((key) => Number(key))
    .filter((id) => Number.isInteger(id) && id < 0);
  if (ids.length === 0) {
    return -1;
  }
  return Math.min(...ids) - 1;
}

function toNumber(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function formatAmount(value) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function getInputValue(id) {
  const node = document.getElementById(id);
  if (node instanceof HTMLInputElement || node instanceof HTMLSelectElement) {
    return node.value;
  }
  return "";
}

function setInputValue(id, value) {
  const node = document.getElementById(id);
  if (node instanceof HTMLInputElement || node instanceof HTMLSelectElement) {
    node.value = value;
  }
}

function getChecked(id) {
  const node = document.getElementById(id);
  return node instanceof HTMLInputElement ? node.checked : false;
}

function setChecked(id, value) {
  const node = document.getElementById(id);
  if (node instanceof HTMLInputElement) {
    node.checked = value;
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
