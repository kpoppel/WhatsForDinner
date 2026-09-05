import { state, persistCache, queueCreateChange, queueDeleteChange, queueUpdateChange } from "./js/state.js";
import { refresh, run, syncPending } from "./js/sync.js";
import { isOnline, apiUpload } from "./js/api.js";

const VIEW_KEY = "wfd.shop-editor.view.v1";
const SEGMENT_DEFAULT = "store";
const STEP = 0.5;
const MIN_SYNCED_AMOUNT = 0.1;

const listNode = document.getElementById("wf-editor-list");
const statusNode = document.getElementById("wf-editor-status");
const dueBannerNode = document.getElementById("wf-editor-due-banner");
const addButton = document.getElementById("wf-editor-add-btn");
const clearAllButton = document.getElementById("wf-editor-clear-all-btn");
const cameraButton = document.getElementById("wf-editor-camera-btn");
const cameraInput = document.getElementById("wf-editor-camera-input");
const segmentButtons = Array.from(document.querySelectorAll("[data-editor-view]"));

const addModal = document.getElementById("wf-editor-add-modal");
const editModal = document.getElementById("wf-editor-edit-modal");
const editUnitLabel = document.getElementById("wf-edit-unit-label");
const mergePickModal = document.getElementById("wf-editor-merge-pick-modal");
const mergePickList = document.getElementById("wf-merge-pick-list");
const mergePickTitle = document.getElementById("wf-editor-merge-pick-title");

const ocrModal = document.getElementById("wf-ocr-review-modal");
const ocrLoadingNode = document.getElementById("wf-ocr-review-loading");
const ocrErrorNode = document.getElementById("wf-ocr-review-error");
const ocrErrorMessageNode = document.getElementById("wf-ocr-review-error-message");
const ocrResultsNode = document.getElementById("wf-ocr-review-results");
const ocrCategorySelect = document.getElementById("wf-ocr-category");
const ocrList = document.getElementById("wf-ocr-review-list");

if (
  !listNode || !statusNode || !dueBannerNode || !addButton || !addModal || !editModal ||
  !editUnitLabel || !mergePickModal || !mergePickList || !mergePickTitle ||
  !cameraButton || !cameraInput || !clearAllButton || !ocrModal || !ocrLoadingNode || !ocrErrorNode ||
  !ocrErrorMessageNode || !ocrResultsNode || !ocrCategorySelect || !ocrList
) {
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

  cameraButton.addEventListener("click", () => {
    cameraInput.click();
  });

  clearAllButton.addEventListener("click", () => {
    run(clearAllItems);
  });

  cameraInput.addEventListener("change", () => {
    const file = cameraInput.files?.[0];
    cameraInput.value = "";
    if (!(file instanceof File)) {
      return;
    }
    openOcrModal();
    run(() => submitOcrPhoto(file));
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

  window.addEventListener("wfd:data-changed", (event) => {
    const detail = event instanceof CustomEvent ? event.detail : null;
    const source = detail && typeof detail === "object" ? String(detail.source || "") : "";
    if (source === "shop-editor") {
      return;
    }
    renderEditor();
  });
}

function bindModalControls() {
  document.getElementById("wf-add-cancel")?.addEventListener("click", closeAddModal);
  document.getElementById("wf-add-save")?.addEventListener("click", () => {
    run(saveAddModal);
  });

  document.getElementById("wf-merge-pick-cancel")?.addEventListener("click", closeMergePickModal);
  mergePickModal.addEventListener("click", (event) => {
    if (event.target === mergePickModal) {
      closeMergePickModal();
    }
  });

  document.getElementById("wf-edit-cancel")?.addEventListener("click", closeEditModal);
  document.getElementById("wf-edit-save")?.addEventListener("click", () => {
    run(saveEditModal);
  });
  document.getElementById("wf-edit-delete")?.addEventListener("click", () => {
    run(deleteFromEditModal);
  });

  document.getElementById("wf-ocr-review-cancel")?.addEventListener("click", closeOcrModal);
  document.getElementById("wf-ocr-review-error-cancel")?.addEventListener("click", closeOcrModal);
  document.getElementById("wf-ocr-review-error-retry")?.addEventListener("click", () => {
    if (pendingOcrFile) {
      showOcrLoadingState();
      run(() => submitOcrPhoto(pendingOcrFile));
    }
  });
  document.getElementById("wf-ocr-review-add-line")?.addEventListener("click", () => {
    ocrList.appendChild(createOcrReviewRow(""));
  });
  document.getElementById("wf-ocr-review-save")?.addEventListener("click", () => {
    run(saveOcrReviewModal);
  });
}

function allItems() {
  return Object.values(state.itemsById)
    .filter((row) => row && row.id !== undefined && row.id !== null)
    .sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
}

function formatMergedAmount(value) {
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
  const amountText = formatMergedAmount(amount);
  const unitText = String(unit || "").trim();
  if (!amountText) {
    return unitText;
  }
  return unitText ? `${amountText} ${unitText}` : amountText;
}

function recipeInfo(item) {
  const raw = item && typeof item.recipe === "object" ? item.recipe : null;
  const recipeId = Number.isInteger(raw?.id) ? raw.id : null;
  const recipeName = String(raw?.name || item?.recipe_context || "Unassigned").trim() || "Unassigned";
  const recipeImage = String(raw?.image || "");
  return {
    id: recipeId,
    name: recipeName,
    image: recipeImage,
  };
}

function recipeGroup(item) {
  const recipe = recipeInfo(item);
  if (recipe.id !== null) {
    return {
      key: `recipe:${recipe.id}`,
      label: recipe.name,
      sortLabel: recipe.name,
    };
  }
  const normalized = recipe.name.toLowerCase();
  return {
    key: `recipe-name:${normalized}`,
    label: recipe.name,
    sortLabel: recipe.name,
  };
}

function storeGroupName(item) {
  const group = item?.store_group;
  if (group && typeof group === "object") {
    const text = String(group.name || "").trim();
    if (text) {
      return text;
    }
  }
  return "General";
}

function aggregateStoreItems(items) {
  const buckets = new Map();

  for (const item of items) {
    const foodId = Number.isInteger(item.food_id) ? item.food_id : null;
    const status = String(item.status || "remaining");
    const key = foodId !== null ? `food:${foodId}|status:${status}` : `entry:${item.id}|status:${status}`;

    let bucket = buckets.get(key);
    if (!bucket) {
      bucket = {
        sample: item,
        entryIds: [],
        units: new Map(),
        recipeSet: new Set(),
      };
      buckets.set(key, bucket);
    }

    if (Number.isInteger(item.id)) {
      bucket.entryIds.push(item.id);
    }
    bucket.recipeSet.add(recipeInfo(item).name);

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
    }
  }

  const merged = [];
  for (const bucket of buckets.values()) {
    const sample = bucket.sample;
    const amountLines = Array.from(bucket.units.values())
      .sort((a, b) => String(a.unit || "").localeCompare(String(b.unit || "")))
      .map((row) => amountLine(row.amount, row.unit));

    const recipeContexts = Array.from(bucket.recipeSet);
    const mixedRecipes = recipeContexts.length > 1;

    merged.push({
      ...sample,
      recipe_context: mixedRecipes ? "Multiple recipes" : (recipeContexts[0] || String(sample.recipe_context || "Unassigned")),
      amount_lines: amountLines,
      entry_ids: bucket.entryIds.length > 0
        ? bucket.entryIds
        : (Number.isInteger(sample.id) ? [sample.id] : []),
      grouped_count: bucket.entryIds.length,
    });
  }

  return merged.sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
}

function groupKey(item, view) {
  if (view === "recipe") {
    return recipeGroup(item);
  }
  const group = item.store_group;
  if (group && typeof group === "object") {
    const label = String(group.name || "General");
    return {
      key: `store:${label.toLowerCase()}`,
      label,
      sortLabel: label,
    };
  }
  return {
    key: "store:general",
    label: "General",
    sortLabel: "General",
  };
}

function groupedItems() {
  const view = activeView();
  const groups = new Map();
  for (const item of allItems()) {
    const group = groupKey(item, view);
    if (!groups.has(group.key)) {
      groups.set(group.key, {
        label: group.label,
        sortLabel: group.sortLabel,
        items: [],
      });
    }
    groups.get(group.key).items.push(item);
  }

  return Array.from(groups.values())
    .map(({ label, sortLabel, items }) => {
      if (view === "store") {
        return [label, aggregateStoreItems(items), sortLabel];
      }
      return [label, items, sortLabel];
    })
    .sort((a, b) => String(a[2] || "").localeCompare(String(b[2] || "")))
    .map(([label, items]) => [label, items]);
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

function suppressNextRowClick(row) {
  row.dataset.suppressNextClick = "1";
}

function consumeSuppressedRowClick(row) {
  if (row.dataset.suppressNextClick === "1") {
    row.dataset.suppressNextClick = "0";
    return true;
  }
  return false;
}

async function deleteEditorEntries(entryIds) {
  const ids = Array.from(new Set(entryIds.map((value) => Number(value)).filter((value) => Number.isInteger(value) && value !== 0)));
  if (ids.length === 0) {
    return;
  }

  for (const entryId of ids) {
    queueDeleteChange(entryId);
  }
  renderEditor();

  if (isOnline()) {
    await syncPending(false);
  }

  renderEditor();
  setStatus(isOnline()
    ? (ids.length === 1 ? "Item deleted." : `${ids.length} items deleted.`)
    : "Offline: delete queued.");
  publishDataChanged();
}

function attachSwipeRightDeleteGesture(row, entryIds) {
  let startX = 0;
  let startY = 0;
  let deltaX = 0;
  let isDragging = false;

  row.addEventListener("touchstart", (event) => {
    const touch = event.changedTouches?.[0];
    if (!touch) {
      return;
    }
    startX = touch.clientX;
    startY = touch.clientY;
    deltaX = 0;
    isDragging = false;
    row.classList.remove("swiping-delete-right");
    row.style.setProperty("--wf-editor-delete-progress", "0");
  });

  row.addEventListener("touchmove", (event) => {
    const touch = event.changedTouches?.[0];
    if (!touch) {
      return;
    }
    deltaX = touch.clientX - startX;
    const deltaY = touch.clientY - startY;
    if (Math.abs(deltaX) <= Math.abs(deltaY) || deltaX <= 0) {
      return;
    }
    isDragging = true;
    const clamped = Math.max(Math.min(deltaX, 130), 0);
    row.style.transform = `translateX(${clamped}px)`;
    row.classList.toggle("swiping-delete-right", clamped > 18);
    const progress = Math.min(Math.abs(clamped) / 130, 1);
    row.style.setProperty("--wf-editor-delete-progress", String(progress));
    if (event.cancelable) {
      event.preventDefault();
    }
  }, { passive: false });

  row.addEventListener("touchend", () => {
    const shouldDelete = isDragging && deltaX > 78;
    row.style.transform = "";
    row.classList.remove("swiping-delete-right");
    row.style.setProperty("--wf-editor-delete-progress", "0");
    if (shouldDelete) {
      suppressNextRowClick(row);
      run(() => deleteEditorEntries(entryIds));
    }
    isDragging = false;
    deltaX = 0;
  });
}

function itemAmountLabel(item) {
  const amount = Number(item?.amount ?? 0);
  const safeAmount = Number.isFinite(amount) ? amount : 0;
  const unit = String(item?.unit || "").trim();
  return `${formatAmount(safeAmount)}${unit ? ` ${unit}` : ""}`.trim();
}

function openMergedItemPicker(groupedItem, entryIds) {
  const items = Array.from(new Set(entryIds))
    .map((entryId) => state.itemsById[String(entryId)])
    .filter((item) => item && item.id !== undefined && item.id !== null)
    .sort((a, b) => {
      const recipeA = recipeInfo(a).name;
      const recipeB = recipeInfo(b).name;
      const recipeCmp = recipeA.localeCompare(recipeB);
      if (recipeCmp !== 0) {
        return recipeCmp;
      }
      return itemAmountLabel(a).localeCompare(itemAmountLabel(b));
    });

  if (items.length === 0) {
    setStatus("No editable entries found for this merged item.");
    return;
  }
  if (items.length === 1) {
    openEditModal(items[0]);
    return;
  }

  mergePickTitle.textContent = `Select Item to Edit (${String(groupedItem.name || "Item")})`;
  mergePickList.innerHTML = "";

  for (const item of items) {
    const recipe = recipeInfo(item);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "wf-merge-pick-item";
    button.setAttribute("role", "listitem");
    button.innerHTML = `
      <span class="wf-merge-pick-main">${escapeHtml(item.name || "Unnamed")}</span>
      <span class="wf-merge-pick-meta">${escapeHtml(recipe.name)} • ${escapeHtml(storeGroupName(item))}</span>
      <span class="wf-merge-pick-amount">${escapeHtml(itemAmountLabel(item))}</span>
    `;
    button.addEventListener("click", () => {
      closeMergePickModal();
      openEditModal(item);
    });
    mergePickList.appendChild(button);
  }

  mergePickModal.hidden = false;
}

function closeMergePickModal() {
  mergePickModal.hidden = true;
  mergePickList.innerHTML = "";
}

function createEditorRow(item) {
  const row = document.createElement("article");
  row.className = "wf-editor-item";

  const status = String(item?.status || "remaining");
  if (status === "completed") {
    row.classList.add("wf-editor-item-status-completed");
  } else if (status === "skipped") {
    row.classList.add("wf-editor-item-status-skipped");
  }

  const entryIds = Array.isArray(item.entry_ids) && item.entry_ids.length > 0
    ? item.entry_ids
    : [item.id];
  const isGrouped = entryIds.length > 1;

  const amount = Number(item.amount ?? 0);
  const safeAmount = Number.isFinite(amount) ? amount : 0;
  const unit = String(item.unit || "").trim();
  const reminderOn = Boolean(item.reminder_enabled);
  const recipe = recipeInfo(item);

  const amountLines = Array.isArray(item.amount_lines) && item.amount_lines.length > 0
    ? item.amount_lines
    : [`${formatAmount(safeAmount)}${unit ? ` ${unit}` : ""}`.trim()];
  const amountMarkup = amountLines
    .map((line) => `<span class="wf-editor-amount-line">${escapeHtml(line)}</span>`)
    .join("");

  if (isGrouped) {
    const groupedRecipeNames = Array.from(new Set(
      entryIds
        .map((entryId) => recipeInfo(state.itemsById[String(entryId)]).name)
        .filter((name) => String(name || "").trim().length > 0)
    )).sort((a, b) => a.localeCompare(b));
    const firstRecipeName = groupedRecipeNames[0] || recipe.name;
    const extraRecipeCount = Math.max(0, groupedRecipeNames.length - 1);
    const recipeSummary = extraRecipeCount > 0
      ? `${firstRecipeName}, +${extraRecipeCount}`
      : firstRecipeName;

    row.classList.add("is-grouped");
    row.innerHTML = `
      <div class="wf-editor-swipe-delete-right-hint" aria-hidden="true">
        <span class="wf-editor-swipe-delete-right-icon">x</span>
        <span class="wf-editor-swipe-delete-right-label">Delete</span>
      </div>
      <div class="wf-editor-main">
        <p class="wf-editor-name">${escapeHtml(item.name || "Unnamed")}</p>
        <p class="wf-editor-meta">${escapeHtml(recipeSummary)}</p>
        <p class="wf-editor-meta wf-editor-meta-store">${escapeHtml(storeGroupName(item))}</p>
      </div>
      <div class="wf-editor-actions">
        <div class="wf-stepper-value wf-stepper-value-stacked">${amountMarkup}</div>
      </div>
    `;

    row.addEventListener("click", () => {
      if (consumeSuppressedRowClick(row)) {
        return;
      }
      openMergedItemPicker(item, entryIds);
    });
    attachSwipeRightDeleteGesture(row, entryIds);
    return row;
  }

  row.innerHTML = `
    <div class="wf-editor-swipe-delete-right-hint" aria-hidden="true">
      <span class="wf-editor-swipe-delete-right-icon">x</span>
      <span class="wf-editor-swipe-delete-right-label">Delete</span>
    </div>
    <div class="wf-editor-main">
      <p class="wf-editor-name">${escapeHtml(item.name || "Unnamed")}</p>
      <p class="wf-editor-meta">${escapeHtml(recipe.name)}</p>
      <p class="wf-editor-meta wf-editor-meta-store">${escapeHtml(storeGroupName(item))}</p>
    </div>
    <div class="wf-editor-actions">
      <button class="wf-bell-btn ${reminderOn ? "is-on" : ""}" type="button" data-action="toggle-reminder">🔔</button>
      <div class="wf-stepper" role="group" aria-label="Quantity controls">
        <button class="wf-stepper-btn" type="button" data-action="decrement">-</button>
        <span class="wf-stepper-value">${amountMarkup}</span>
        <button class="wf-stepper-btn" type="button" data-action="increment">+</button>
      </div>
    </div>
  `;
  row.classList.add("wf-editor-item-compact");

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
    if (consumeSuppressedRowClick(row)) {
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    if (target.closest(".wf-editor-actions")) {
      return;
    }
    openEditModal(item);
  });

  attachSwipeRightDeleteGesture(row, entryIds);

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
    renderEditor();
    setStatus("Item added.");
    publishDataChanged();
  } else {
    setStatus("Offline: item queued and will sync when online.");
    publishDataChanged();
  }

  closeAddModal();
}

let pendingOcrFile = null;

function openOcrModal() {
  ocrModal.hidden = false;
  showOcrLoadingState();
}

function closeOcrModal() {
  ocrModal.hidden = true;
  pendingOcrFile = null;
  ocrList.innerHTML = "";
}

function showOcrLoadingState() {
  ocrLoadingNode.hidden = false;
  ocrErrorNode.hidden = true;
  ocrResultsNode.hidden = true;
}

function showOcrErrorState(message) {
  ocrLoadingNode.hidden = true;
  ocrErrorNode.hidden = false;
  ocrResultsNode.hidden = true;
  ocrErrorMessageNode.textContent = message;
}

function showOcrResultsState(items) {
  ocrLoadingNode.hidden = true;
  ocrErrorNode.hidden = true;
  ocrResultsNode.hidden = false;

  const categories = serverStoreGroupNames();
  const initialCategory = categories.includes("Other") ? "Other" : (categories[0] || "Other");
  populateCategorySelect("wf-ocr-category", initialCategory);

  ocrList.innerHTML = "";
  for (const item of items) {
    ocrList.appendChild(createOcrReviewRow(item));
  }
}

function createOcrReviewRow(text) {
  const row = document.createElement("div");
  row.className = "wf-ocr-review-row";
  row.setAttribute("role", "listitem");

  const input = document.createElement("input");
  input.type = "text";
  input.maxLength = 120;
  input.value = text;
  row.appendChild(input);

  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.className = "wf-ocr-review-remove";
  removeButton.setAttribute("aria-label", "Remove line");
  removeButton.textContent = "×";
  removeButton.addEventListener("click", () => {
    row.remove();
  });
  row.appendChild(removeButton);

  return row;
}

async function submitOcrPhoto(file) {
  pendingOcrFile = file;
  showOcrLoadingState();

  let response;
  try {
    const formData = new FormData();
    formData.append("image", file);
    response = await apiUpload("/shopping-list/ocr", formData);
  } catch (error) {
    showOcrErrorState("Could not read the photo. Check your connection and try again.");
    return;
  }

  const items = Array.isArray(response?.items) ? response.items : [];
  if (items.length === 0) {
    showOcrErrorState("No text was recognized in that photo. Try again with a clearer shot.");
    return;
  }

  showOcrResultsState(items);
}

async function saveOcrReviewModal() {
  const category = getInputValue("wf-ocr-category").trim() || "Other";
  const names = Array.from(ocrList.querySelectorAll("input"))
    .map((input) => input.value.trim())
    .filter((name) => name.length > 0);

  if (names.length === 0) {
    throw new Error("Add at least one item before saving.");
  }

  let tempId = nextTempId();
  for (const name of names) {
    const payload = {
      id: tempId,
      ad_hoc: true,
      name,
      amount: 0,
      unit: "",
      ingredient_type: "Other",
      store_group: { id: null, name: category },
      recipe_context: "Unassigned",
      status: "remaining",
      reminder_enabled: false,
      reminder_date: null,
      reminder_text: "",
    };
    queueCreateChange(payload);
    tempId -= 1;
  }
  renderEditor();

  if (isOnline()) {
    await syncPending(false);
    await refresh();
    renderEditor();
    setStatus(names.length === 1 ? "Item added." : `${names.length} items added.`);
    publishDataChanged();
  } else {
    setStatus(`Offline: ${names.length} item${names.length === 1 ? "" : "s"} queued and will sync when online.`);
    publishDataChanged();
  }

  closeOcrModal();
}

function openEditModal(item) {
  editModal.hidden = false;
  setInputValue("wf-edit-entry-id", String(item.id));
  setInputValue("wf-edit-name", String(item.name || ""));
  setInputValue("wf-edit-amount", String(item.amount ?? 0));
  const unitText = String(item.unit || "").trim();
  editUnitLabel.textContent = unitText;
  editUnitLabel.hidden = !unitText;
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
  }

  closeEditModal();
  renderEditor();
  setStatus(isOnline() ? "Item deleted." : "Offline: delete queued.");
  publishDataChanged();
}

async function clearAllItems() {
  const allItems = Object.values(state.itemsById).filter((item) => item && item.id !== undefined && item.id !== null);
  if (allItems.length === 0) {
    setStatus("No items to clear.");
    return;
  }

  if (!window.confirm(`Clear all ${allItems.length} item(s) from the shopping list? This action will also remove them from Tandoor.`)) {
    return;
  }

  for (const item of allItems) {
    queueDeleteChange(item.id);
  }
  renderEditor();

  if (isOnline()) {
    await syncPending(false);
  }

  renderEditor();
  setStatus(isOnline() ? `${allItems.length} item(s) cleared.` : "Offline: deletions queued.");
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
