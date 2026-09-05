import {
  cachePlanDetail,
  cachePlanListRows,
  writeActiveMealPlanId,
} from "./js/store/commands.js";
import {
  createMealPlanEntry,
  deleteMealPlanEntry,
  deleteStoredMealPlan,
  generateMealPlan,
  generateMealPlanShoppingList,
  loadMealPlan,
  loadMealPlanDefaultDiners,
  loadStoredMealPlans,
  searchMealPlanRecipes,
  updateMealPlanEntry,
  updateMealPlanStartDate,
} from "./js/commands/meal-plans.js";
import { setApiReachable } from "./js/commands/connectivity.js";
import { isOnline } from "./js/selectors/connectivity.js";
import { readMealPlanCache } from "./js/store/selectors.js";
import { assertRequiredFields } from "./js/contracts.js";

(() => {
  const changeStartDateButton = document.getElementById("wf-plan-change-start-btn");
  const addDayButton = document.getElementById("wf-plan-add-day-btn");
  const generateShoppingButton = document.getElementById("wf-plan-generate-shopping-btn");
  const listNode = document.getElementById("wf-plan-list");
  const detailNode = document.getElementById("wf-plan-detail");
  const detailTitleNode = document.getElementById("wf-plan-detail-title");
  const detailRangeNode = document.getElementById("wf-plan-detail-range");
  const statusNode = document.getElementById("wf-plan-status");
  const generateButton = document.getElementById("wf-plan-generate-btn");

  const generateModal = document.getElementById("wf-plan-generate-modal");
  const generateStartDateInput = document.getElementById("wf-plan-start-date");
  const generateLengthInput = document.getElementById("wf-plan-length-days");
  const generateDinersInput = document.getElementById("wf-plan-diners");
  const generateCancelButton = document.getElementById("wf-plan-generate-cancel");
  const generateSaveButton = document.getElementById("wf-plan-generate-save");

  const startDateModal = document.getElementById("wf-plan-start-date-modal");
  const startDateEditInput = document.getElementById("wf-plan-start-date-edit");
  const startDateCancelButton = document.getElementById("wf-plan-start-date-cancel");
  const startDateSaveButton = document.getElementById("wf-plan-start-date-save");

  const mealEditorModal = document.getElementById("wf-meal-editor-modal");
  const mealEditorEntryIdInput = document.getElementById("wf-meal-editor-entry-id");
  const mealEditorNameField = document.getElementById("wf-meal-editor-name-field");
  const mealEditorNameInput = document.getElementById("wf-meal-editor-name");
  const mealEditorRecipesField = document.getElementById("wf-meal-editor-recipes-field");
  const mealEditorRecipesList = document.getElementById("wf-meal-editor-recipes-list");
  const mealEditorRecipesAddButton = document.getElementById("wf-meal-editor-recipes-add-btn");
  const mealEditorRecipesAddRow = document.getElementById("wf-meal-editor-recipes-add-row");
  const mealEditorRecipesSearchInput = document.getElementById("wf-meal-editor-recipes-search");
  const mealEditorRecipesSearchResults = document.getElementById("wf-meal-editor-recipes-search-results");
  const mealEditorRecipesPurpose = document.getElementById("wf-meal-editor-recipes-purpose");
  const mealEditorRecipesAddCancel = document.getElementById("wf-meal-editor-recipes-add-cancel");
  const mealEditorModes = Array.from(document.querySelectorAll("#wf-meal-editor-modes [data-mode]"));
  const mealEditorDinersField = document.getElementById("wf-meal-editor-diners-field");
  const mealEditorDinersDown = document.getElementById("wf-meal-editor-diners-down");
  const mealEditorDinersUp = document.getElementById("wf-meal-editor-diners-up");
  const mealEditorDinersValue = document.getElementById("wf-meal-editor-diners-value");
  const mealEditorReminderField = document.getElementById("wf-meal-editor-reminder-field");
  const mealEditorReminderEnabled = document.getElementById("wf-meal-editor-reminder-enabled");
  const mealEditorReminderText = document.getElementById("wf-meal-editor-reminder-text");
  const mealEditorCancelButton = document.getElementById("wf-meal-editor-cancel");
  const mealEditorSaveButton = document.getElementById("wf-meal-editor-save");

  if (
    !(changeStartDateButton instanceof HTMLButtonElement) ||
    !(addDayButton instanceof HTMLButtonElement) ||
    !(generateShoppingButton instanceof HTMLButtonElement) ||
    !(listNode instanceof HTMLElement) ||
    !(detailNode instanceof HTMLElement) ||
    !(detailTitleNode instanceof HTMLElement) ||
    !(detailRangeNode instanceof HTMLElement) ||
    !(statusNode instanceof HTMLElement) ||
    !(generateButton instanceof HTMLButtonElement) ||
    !(generateModal instanceof HTMLElement) ||
    !(generateStartDateInput instanceof HTMLInputElement) ||
    !(generateLengthInput instanceof HTMLInputElement) ||
    !(generateDinersInput instanceof HTMLInputElement) ||
    !(generateCancelButton instanceof HTMLButtonElement) ||
    !(generateSaveButton instanceof HTMLButtonElement) ||
    !(startDateModal instanceof HTMLElement) ||
    !(startDateEditInput instanceof HTMLInputElement) ||
    !(startDateCancelButton instanceof HTMLButtonElement) ||
    !(startDateSaveButton instanceof HTMLButtonElement) ||
    !(mealEditorModal instanceof HTMLElement) ||
    !(mealEditorEntryIdInput instanceof HTMLInputElement) ||
    !(mealEditorNameField instanceof HTMLElement) ||
    !(mealEditorNameInput instanceof HTMLInputElement) ||
    !(mealEditorRecipesField instanceof HTMLElement) ||
    !(mealEditorRecipesList instanceof HTMLElement) ||
    !(mealEditorRecipesAddButton instanceof HTMLButtonElement) ||
    !(mealEditorRecipesAddRow instanceof HTMLElement) ||
    !(mealEditorRecipesSearchInput instanceof HTMLInputElement) ||
    !(mealEditorRecipesSearchResults instanceof HTMLElement) ||
    !(mealEditorRecipesPurpose instanceof HTMLElement) ||
    !(mealEditorRecipesAddCancel instanceof HTMLButtonElement) ||
    !(mealEditorDinersField instanceof HTMLElement) ||
    !(mealEditorDinersDown instanceof HTMLButtonElement) ||
    !(mealEditorDinersUp instanceof HTMLButtonElement) ||
    !(mealEditorDinersValue instanceof HTMLElement) ||
    !(mealEditorReminderField instanceof HTMLElement) ||
    !(mealEditorReminderEnabled instanceof HTMLInputElement) ||
    !(mealEditorReminderText instanceof HTMLInputElement) ||
    !(mealEditorCancelButton instanceof HTMLButtonElement) ||
    !(mealEditorSaveButton instanceof HTMLButtonElement)
  ) {
    return;
  }

  const shortDate = new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  });

  const longDate = new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });

  const generateSheetClass = "wf-plan-sheet-open";
  let activePlanId = null;
  let selectedPlanId = null;
  const planPreviewTitlesById = new Map();
  let generateModalClosing = false;

  let editorRecipes = [];
  let editorMode = "planned";
  let editorServings = 2;
  let editorSearchTimer = 0;
  let editorAddRecipePurpose = "meal";
  let editorMealTitleManuallySet = false;
  let mealEditorClosing = false;

  let draggedEntryId = null;
  let touchDraggedEntryId = null;
  let touchDropEntryId = null;
  let touchDropPlacement = "before";
  let generateShoppingInFlight = false;
  let generateShoppingLongPressTimer = 0;
  let generateShoppingLongPressTriggered = false;
  let generateShoppingSuppressClick = false;
  let mealPlanActionQueue = Promise.resolve();
  let mealPlanReorderRevision = 0;

  const GENERATE_SHOPPING_LONG_PRESS_MS = 700;

  function cachedPlanDetail(planId) {
    const cache = readMealPlanCache();
    const row = cache.byId[String(planId)];
    if (row && typeof row === "object") {
      return row;
    }
    return null;
  }

  function selectedPlanDetail() {
    if (!Number.isInteger(selectedPlanId)) {
      return null;
    }
    return cachedPlanDetail(selectedPlanId);
  }

  function isMealPlanOfflineReadOnly() {
    return !isOnline();
  }

  function reportApiReachable(value) {
    setApiReachable(value);
  }

  function assertMealPlanWriteAllowed(action) {
    if (isMealPlanOfflineReadOnly()) {
      throw new Error(`Cannot ${action} while offline. Meal plan editing is disabled.`);
    }
  }

  function updateMealPlanActionAvailability() {
    const isOffline = isMealPlanOfflineReadOnly();
    generateButton.disabled = isOffline;
    changeStartDateButton.disabled = isOffline;
    addDayButton.disabled = isOffline;
    generateShoppingButton.disabled = isOffline;
    if (isOffline) {
      generateButton.title = "Offline: generation is unavailable.";
      changeStartDateButton.title = "Offline: updating plan date is unavailable.";
      addDayButton.title = "Offline: adding days is unavailable.";
      generateShoppingButton.title = "Offline: shopping-list generation is unavailable.";
      return;
    }
    generateButton.title = "";
    changeStartDateButton.title = "";
    addDayButton.title = "";
    generateShoppingButton.title = "";
  }

  function setStatus(message) {
    statusNode.textContent = message;
  }

  function setGenerateShoppingLongPressActive(isActive) {
    generateShoppingButton.classList.toggle("is-long-press-active", isActive);
  }

  function publishDataChanged() {
    window.dispatchEvent(new CustomEvent("wfd:data-changed", { detail: { source: "meal-plans" } }));
  }

  function setAppTab(tabName) {
    if (typeof window.WFD_setActiveTab === "function") {
      window.WFD_setActiveTab(tabName);
      return;
    }

    const panelNodes = Array.from(document.querySelectorAll("[data-tab-panel]"));
    for (const panel of panelNodes) {
      const isTarget = panel.dataset.tabPanel === tabName;
      panel.hidden = !isTarget;
      panel.classList.toggle("is-active", isTarget);
    }
  }

  function toIsoDate(nowDate) {
    const year = nowDate.getFullYear();
    const month = String(nowDate.getMonth() + 1).padStart(2, "0");
    const day = String(nowDate.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function parseIsoDate(text) {
    if (typeof text !== "string") {
      return null;
    }

    const parsed = new Date(`${text}T00:00:00`);
    if (Number.isNaN(parsed.getTime())) {
      return null;
    }

    return parsed;
  }

  function addDays(sourceDate, amount) {
    const clone = new Date(sourceDate.getTime());
    clone.setDate(clone.getDate() + amount);
    return clone;
  }

  function planDateRangeLabel(plan) {
    const startRaw = String(plan.start_date);
    const startDate = parseIsoDate(startRaw);
    if (startDate === null) {
      return startRaw;
    }

    const lengthDays = Number(plan.length_days);
    if (!Number.isInteger(lengthDays) || lengthDays < 1) {
      return shortDate.format(startDate);
    }

    const endDate = addDays(startDate, lengthDays - 1);
    return `${shortDate.format(startDate)} - ${shortDate.format(endDate)}`;
  }

  function planListDateRangeLabel(plan) {
    const startRaw = String(plan.start_date);
    const startDate = parseIsoDate(startRaw);
    if (startDate === null) {
      return startRaw;
    }

    const lengthDays = Number(plan.length_days);
    if (!Number.isInteger(lengthDays) || lengthDays < 1) {
      return toIsoDate(startDate);
    }

    const endDate = addDays(startDate, lengthDays - 1);
    return `${toIsoDate(startDate)} - ${toIsoDate(endDate)}`;
  }

  function planMetaText(plan) {
    const lengthDays = Number(plan.length_days);
    const entryCount = Number(plan.entry_count);
    const dayText = lengthDays === 1 ? "Day" : "Days";
    const mealText = entryCount === 1 ? "Meal Planned" : "Meals Planned";
    return `${lengthDays} ${dayText} • ${entryCount} ${mealText}`;
  }

  function buildPlanPreviewTitles(entries) {
    if (!Array.isArray(entries) || entries.length === 0) {
      return [];
    }

    const titles = [];
    const seen = new Set();
    for (const entry of entries) {
      const title = entryRecipeTitle(entry).trim();
      const key = title.toLowerCase();
      if (title.length === 0 || seen.has(key)) {
        continue;
      }
      seen.add(key);
      titles.push(title);
      if (titles.length >= 3) {
        break;
      }
    }

    return titles;
  }

  function cachePlanPreview(plan) {
    const planId = Number(plan?.plan_id);
    if (!Number.isInteger(planId)) {
      return;
    }

    planPreviewTitlesById.set(planId, buildPlanPreviewTitles(plan?.entries));
  }

  function planIncludesText(plan) {
    const planId = Number(plan?.plan_id);
    const titles = Number.isInteger(planId) ? planPreviewTitlesById.get(planId) : null;

    if (!Array.isArray(titles) || titles.length === 0) {
      return "Includes: Open plan to view meals.";
    }

    const entryCount = Number(plan?.entry_count);
    const preview = titles.join(", ");
    if (Number.isInteger(entryCount) && entryCount > titles.length) {
      return `Includes: ${preview}...`;
    }
    return `Includes: ${preview}`;
  }

  function sortPlansMostRecentFirst(plans) {
    if (!Array.isArray(plans)) {
      return [];
    }

    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());

    const sorted = [...plans];
    sorted.sort((left, right) => {
      const leftDate = parseIsoDate(String(left?.start_date || ""));
      const rightDate = parseIsoDate(String(right?.start_date || ""));

      const leftDistance = leftDate ? Math.abs(Math.round((leftDate.getTime() - today.getTime()) / 86400000)) : Number.POSITIVE_INFINITY;
      const rightDistance = rightDate ? Math.abs(Math.round((rightDate.getTime() - today.getTime()) / 86400000)) : Number.POSITIVE_INFINITY;
      if (leftDistance !== rightDistance) {
        return leftDistance - rightDistance;
      }

      const leftFutureOrToday = leftDate ? (leftDate.getTime() >= today.getTime() ? 0 : 1) : 1;
      const rightFutureOrToday = rightDate ? (rightDate.getTime() >= today.getTime() ? 0 : 1) : 1;
      if (leftFutureOrToday !== rightFutureOrToday) {
        return leftFutureOrToday - rightFutureOrToday;
      }

      if (leftDate && rightDate && leftDate.getTime() !== rightDate.getTime()) {
        return rightDate.getTime() - leftDate.getTime();
      }

      const leftId = Number(left?.plan_id);
      const rightId = Number(right?.plan_id);
      if (Number.isInteger(leftId) && Number.isInteger(rightId) && leftId !== rightId) {
        return rightId - leftId;
      }

      return 0;
    });

    return sorted;
  }

  function modeBadge(mode) {
    if (mode === "leftover") {
      return "Leftovers";
    }
    if (mode === "takeout") {
      return "Takeout";
    }
    if (mode === "empty") {
      return "Eating out";
    }
    return "Cook";
  }

  function modeClass(mode) {
    if (mode === "leftover") {
      return "wf-plan-mode wf-plan-mode-leftover";
    }
    if (mode === "takeout") {
      return "wf-plan-mode wf-plan-mode-takeout";
    }
    if (mode === "empty") {
      return "wf-plan-mode wf-plan-mode-empty";
    }
    return "wf-plan-mode wf-plan-mode-cook";
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function entryRecipeTitle(entry) {
    if (entry && typeof entry === "object") {
      const recipe = entry.recipe;
      if (recipe && typeof recipe === "object") {
        if (typeof recipe.title === "string" && recipe.title.trim().length > 0) {
          return recipe.title.trim();
        }
      }
    }
    return "No recipe";
  }

  function parseEntryReminder(entry) {
    let enabled = false;
    let text = "";

    if (entry && typeof entry === "object") {
      if (typeof entry.reminder_enabled === "boolean") {
        enabled = entry.reminder_enabled;
      }
      if (typeof entry.reminder_text === "string") {
        text = entry.reminder_text;
      }

      if ((enabled === false && text.length === 0) && typeof entry.notes === "string") {
        const notesText = entry.notes.trim();
        if (notesText.startsWith("{")) {
          try {
            const parsed = JSON.parse(notesText);
            if (parsed && typeof parsed === "object") {
              if (typeof parsed.reminder_enabled === "boolean") {
                enabled = parsed.reminder_enabled;
              }
              if (typeof parsed.reminder_text === "string") {
                text = parsed.reminder_text;
              }
            }
          } catch {
            // Ignore malformed legacy notes.
          }
        }
      }
    }

    return { enabled, text };
  }

  function renderPlanList(plans) {
    listNode.innerHTML = "";

    if (!Array.isArray(plans) || plans.length === 0) {
      listNode.innerHTML = '<article class="wf-plan-empty">No meal plans stored yet.</article>';
      return;
    }

    for (const plan of plans) {
      const planId = Number(plan.plan_id);
      const card = document.createElement("article");
      card.className = "wf-plan-card";
      if (planId === activePlanId) {
        card.classList.add("is-active");
      }

      const header = document.createElement("div");
      header.className = "wf-plan-card-head";

      const heading = document.createElement("h3");
      heading.className = "wf-plan-card-title";
      heading.textContent = planListDateRangeLabel(plan);
      header.appendChild(heading);

      if (planId === activePlanId) {
        const badge = document.createElement("span");
        badge.className = "wf-plan-active-badge";
        badge.textContent = "Active";
        header.appendChild(badge);
      }

      const meta = document.createElement("p");
      meta.className = "wf-plan-card-meta";
      meta.textContent = planMetaText(plan);

      const includes = document.createElement("p");
      includes.className = "wf-plan-card-includes";
      includes.textContent = planIncludesText(plan);

      const deleteHint = document.createElement("div");
      deleteHint.className = "wf-plan-card-swipe-delete-right-hint";
      deleteHint.innerHTML = `
        <span class="wf-plan-card-swipe-delete-right-icon">x</span>
        <span class="wf-plan-card-swipe-delete-right-label">Delete Plan</span>
      `;

      card.appendChild(deleteHint);
      card.appendChild(header);
      card.appendChild(meta);
      card.appendChild(includes);

      attachPlanCardSwipeRightDeleteGesture(card, planId);

      card.addEventListener("click", () => {
        if (consumeSuppressedPlanCardClick(card)) {
          return;
        }
        void runAction(() => openPlanEditor(planId));
      });

      listNode.appendChild(card);
    }
  }

  function suppressNextPlanCardClick(card) {
    card.dataset.suppressNextClick = "1";
  }

  function consumeSuppressedPlanCardClick(card) {
    if (card.dataset.suppressNextClick === "1") {
      card.dataset.suppressNextClick = "0";
      return true;
    }
    return false;
  }

  function attachPlanCardSwipeRightDeleteGesture(card, planId) {
    let startX = 0;
    let startY = 0;
    let deltaX = 0;
    let isDragging = false;

    card.addEventListener("touchstart", (event) => {
      if (isMealPlanOfflineReadOnly()) {
        return;
      }

      const touch = event.changedTouches?.[0];
      if (!touch) {
        return;
      }

      startX = touch.clientX;
      startY = touch.clientY;
      deltaX = 0;
      isDragging = false;
      card.classList.remove("swiping-delete-right");
      card.style.setProperty("--wf-plan-card-delete-progress", "0");
    });

    card.addEventListener("touchmove", (event) => {
      if (isMealPlanOfflineReadOnly()) {
        return;
      }

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
      card.style.transform = `translateX(${clamped}px)`;
      card.classList.toggle("swiping-delete-right", clamped > 18);
      const progress = Math.min(Math.abs(clamped) / 130, 1);
      card.style.setProperty("--wf-plan-card-delete-progress", String(progress));
      if (event.cancelable) {
        event.preventDefault();
      }
    }, { passive: false });

    card.addEventListener("touchend", () => {
      const shouldDelete = isDragging && deltaX > 78;
      card.style.transform = "";
      card.classList.remove("swiping-delete-right");
      card.style.setProperty("--wf-plan-card-delete-progress", "0");
      if (shouldDelete) {
        suppressNextPlanCardClick(card);
        void runAction(() => deleteStoredPlan(planId));
      }
      isDragging = false;
      deltaX = 0;
    });
  }

  function clearDayDropTargets() {
    detailNode.querySelectorAll(".wf-plan-day.is-drop-target, .wf-plan-day.is-drop-before, .wf-plan-day.is-drop-after").forEach((node) => {
      node.classList.remove("is-drop-target");
      node.classList.remove("is-drop-before");
      node.classList.remove("is-drop-after");
    });
  }

  function setDropTarget(entryId, placement = "before") {
    clearDayDropTargets();
    if (!Number.isInteger(entryId)) {
      return;
    }

    const target = detailNode.querySelector(`.wf-plan-day[data-entry-id="${entryId}"]`);
    if (target instanceof HTMLElement) {
      target.classList.add("is-drop-target");
      if (placement === "after") {
        target.classList.add("is-drop-after");
      } else {
        target.classList.add("is-drop-before");
      }
    }
  }

  function findEntryById(entryId) {
    const plan = selectedPlanDetail();
    if (!plan) {
      return null;
    }
    const entries = plan.entries;
    if (!Array.isArray(entries)) {
      return null;
    }

    for (const entry of entries) {
      if (!entry || typeof entry !== "object") {
        continue;
      }
      if (Number(entry.entry_id) === entryId) {
        return entry;
      }
    }

    return null;
  }

  function queueReorderEntry(dragEntryId, dropEntryId, dropPlacement = "before") {
    assertMealPlanWriteAllowed("reorder meal days");
    if (!Number.isInteger(selectedPlanId)) {
      return;
    }
    const plan = selectedPlanDetail();
    if (!plan) {
      return;
    }
    if (!Array.isArray(plan.entries)) {
      return;
    }
    if (!Number.isInteger(dragEntryId) || !Number.isInteger(dropEntryId)) {
      return;
    }
    if (dragEntryId === dropEntryId) {
      return;
    }

    const ordered = [...plan.entries].sort((a, b) => Number(a.day_index) - Number(b.day_index));

    let fromIndex = -1;
    let toIndex = -1;

    for (let index = 0; index < ordered.length; index += 1) {
      const entry = ordered[index];
      if (!entry || typeof entry !== "object") {
        continue;
      }
      if (Number(entry.entry_id) === dragEntryId) {
        fromIndex = index;
      }
      if (Number(entry.entry_id) === dropEntryId) {
        toIndex = index;
      }
    }

    if (fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) {
      return;
    }

    const moveAfter = dropPlacement === "after";
    let targetDayIndex = moveAfter ? (toIndex + 1) : toIndex;
    if (fromIndex < targetDayIndex) {
      targetDayIndex -= 1;
    }
    targetDayIndex = Math.max(0, Math.min(targetDayIndex, ordered.length - 1));

    const [movedEntry] = ordered.splice(fromIndex, 1);
    ordered.splice(targetDayIndex, 0, movedEntry);
    cachePlanDetail({
      ...plan,
      entries: ordered.map((entry, index) => ({ ...entry, day_index: index })),
    });
    renderPlanDetail(selectedPlanDetail());
    setStatus("Syncing meal day order...");

    const planId = selectedPlanId;
    mealPlanReorderRevision += 1;
    const reorderRevision = mealPlanReorderRevision;
    void runAction(() => syncReorderEntry(planId, dragEntryId, targetDayIndex, reorderRevision));
  }

  async function syncReorderEntry(planId, dragEntryId, targetDayIndex, reorderRevision) {
    await updateMealPlanEntry(
      planId,
      dragEntryId,
      { target_day_index: targetDayIndex },
      reportApiReachable,
    );

    if (reorderRevision === mealPlanReorderRevision) {
      await reloadSelectedPlan();
      setStatus("Meal day order updated.");
    }
    publishDataChanged();
  }

  function suppressNextDayCardClick(dayCard) {
    dayCard.dataset.suppressNextClick = "1";
  }

  function consumeSuppressedDayCardClick(dayCard) {
    if (dayCard.dataset.suppressNextClick === "1") {
      dayCard.dataset.suppressNextClick = "0";
      return true;
    }
    return false;
  }

  function attachSwipeRightDeleteGesture(dayCard, entryId) {
    let startX = 0;
    let startY = 0;
    let deltaX = 0;
    let isDragging = false;

    dayCard.addEventListener("touchstart", (event) => {
      if (isMealPlanOfflineReadOnly()) {
        return;
      }
      const target = event.target;
      if (target instanceof Element && target.closest('[data-role="drag-handle"]')) {
        return;
      }

      const touch = event.changedTouches?.[0];
      if (!touch) {
        return;
      }

      startX = touch.clientX;
      startY = touch.clientY;
      deltaX = 0;
      isDragging = false;
      dayCard.classList.remove("swiping-delete-right");
      dayCard.style.setProperty("--wf-plan-delete-progress", "0");
    });

    dayCard.addEventListener("touchmove", (event) => {
      if (isMealPlanOfflineReadOnly()) {
        return;
      }
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
      dayCard.style.transform = `translateX(${clamped}px)`;
      dayCard.classList.toggle("swiping-delete-right", clamped > 18);
      const progress = Math.min(Math.abs(clamped) / 130, 1);
      dayCard.style.setProperty("--wf-plan-delete-progress", String(progress));
      if (event.cancelable) {
        event.preventDefault();
      }
    }, { passive: false });

    dayCard.addEventListener("touchend", () => {
      const shouldDelete = isDragging && deltaX > 78;
      dayCard.style.transform = "";
      dayCard.classList.remove("swiping-delete-right");
      dayCard.style.setProperty("--wf-plan-delete-progress", "0");
      if (shouldDelete) {
        suppressNextDayCardClick(dayCard);
        void runAction(() => deleteMealDay(entryId));
      }
      isDragging = false;
      deltaX = 0;
    });
  }

  async function deleteMealDay(entryId) {
    assertMealPlanWriteAllowed("delete a meal day");
    if (!Number.isInteger(selectedPlanId)) {
      throw new Error("No meal plan selected.");
    }
    await deleteMealPlanEntry(selectedPlanId, entryId, reportApiReachable);
    await reloadSelectedPlan();
    setStatus("Meal day deleted.");
    publishDataChanged();
  }

  async function deleteStoredPlan(planId) {
    assertMealPlanWriteAllowed("delete a meal plan");

    await deleteStoredMealPlan(planId, reportApiReachable);

    if (selectedPlanId === planId) {
      selectedPlanId = null;
      writeActiveMealPlanId(null);
      renderPlanDetail(null);
      setAppTab("meal-plans");
    }

    if (activePlanId === planId) {
      activePlanId = null;
    }

    await refreshPlans();
    setStatus("Meal plan deleted.");
    publishDataChanged();
  }

  async function addMealDay() {
    assertMealPlanWriteAllowed("add a meal day");
    if (!Number.isInteger(selectedPlanId)) {
      throw new Error("No meal plan selected.");
    }

    const plan = selectedPlanDetail();
    if (!plan || typeof plan !== "object") {
      throw new Error("Open a meal plan first.");
    }

    const entries = Array.isArray(plan.entries) ? plan.entries : [];
    const nextDayIndex = entries.length;
    const startDate = parseIsoDate(String(plan.start_date));
    const nextDate = startDate ? toIsoDate(addDays(startDate, nextDayIndex)) : "";
    const defaultServings = Number(plan.diners);

    const payload = await createMealPlanEntry(selectedPlanId, {
      day_index: nextDayIndex,
      date: nextDate,
      mode: "planned",
      servings: Number.isInteger(defaultServings) ? defaultServings : 2,
      recipe: null,
    }, reportApiReachable);

    const updatedPlan = payload && typeof payload === "object" ? payload.data : null;
    const updatedEntries = Array.isArray(updatedPlan?.entries) ? updatedPlan.entries : [];
    const createdEntry = updatedEntries.find((row) => Number(row?.day_index) === nextDayIndex) || null;
    const createdEntryId = Number(createdEntry?.entry_id);

    await reloadSelectedPlan();
    if (Number.isInteger(createdEntryId)) {
      await openMealEditor(createdEntryId);
      setStatus(`Added Day ${nextDayIndex + 1}. Edit details and save when ready.`);
    } else {
      setStatus(`Added Day ${nextDayIndex + 1}.`);
    }
    publishDataChanged();
  }

  function renderPlanDetail(plan) {
    detailNode.innerHTML = "";

    if (!plan || typeof plan !== "object") {
      detailTitleNode.textContent = "Plan Detail";
      detailRangeNode.textContent = "-";
      detailNode.innerHTML = '<article class="wf-plan-empty">Select a plan to view day-by-day details.</article>';
      return;
    }

    const rangeLabel = planDateRangeLabel(plan);
    detailRangeNode.textContent = rangeLabel;
    detailTitleNode.textContent = rangeLabel;

    const entries = Array.isArray(plan.entries) ? [...plan.entries] : [];
    entries.sort((a, b) => Number(a.day_index) - Number(b.day_index));

    if (entries.length === 0) {
      detailNode.innerHTML = '<article class="wf-plan-empty">This plan has no entries.</article>';
      return;
    }

    const canEditPlan = !isMealPlanOfflineReadOnly();
    const stack = document.createElement("section");
    stack.className = "wf-plan-days";

    for (const entry of entries) {
      const entryId = Number(entry.entry_id);
      const dayIndex = Number(entry.day_index);
      const mode = String(entry.mode);

      const rawDate = String(entry.date);
      const parsedDate = parseIsoDate(rawDate);
      let dayDate = rawDate;
      if (parsedDate !== null) {
        dayDate = longDate.format(parsedDate);
      }

      const recipeTitle = entryRecipeTitle(entry);
      const reminder = parseEntryReminder(entry);
      const servings = Number(entry.servings);
      const servingsText = Number.isInteger(servings) ? `${servings} diners` : "- diners";

      const dayCard = document.createElement("article");
      dayCard.className = "wf-plan-day";
      if (mode === "leftover") {
        dayCard.classList.add("wf-plan-day-leftover");
      } else if (mode === "takeout") {
        dayCard.classList.add("wf-plan-day-takeout");
      } else if (mode === "empty") {
        dayCard.classList.add("wf-plan-day-empty");
      }
      dayCard.dataset.entryId = String(entryId);
      dayCard.draggable = canEditPlan;

      const reminderBadge = reminder.enabled ? '<span class="wf-badge wf-badge-notify">🔔 Reminder Set</span>' : "";

      dayCard.innerHTML = `
        <div class="wf-plan-swipe-delete-right-hint" aria-hidden="true">
          <span class="wf-plan-swipe-delete-right-icon">x</span>
          <span class="wf-plan-swipe-delete-right-label">Delete Day</span>
        </div>
        <button class="wf-plan-drag-handle" type="button" data-role="drag-handle" aria-label="Drag day">⋮⋮</button>
        <div class="wf-plan-day-body">
          <div class="wf-plan-day-head">
            <p class="wf-plan-day-kicker">Day ${dayIndex + 1} • ${escapeHtml(dayDate)}</p>
            <span class="${modeClass(mode)}">${modeBadge(mode)}</span>
          </div>
          <h4 class="wf-plan-day-title">${escapeHtml(recipeTitle)}</h4>
          <p class="wf-plan-card-meta">👥 ${escapeHtml(servingsText)} ${reminderBadge}</p>
        </div>
      `;

      attachSwipeRightDeleteGesture(dayCard, entryId);

      dayCard.addEventListener("dragstart", (event) => {
        if (isMealPlanOfflineReadOnly()) {
          event.preventDefault();
          return;
        }
        draggedEntryId = entryId;
        dayCard.classList.add("is-dragging");
        if (event.dataTransfer) {
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", String(entryId));
        }
      });

      dayCard.addEventListener("dragover", (event) => {
        if (isMealPlanOfflineReadOnly()) {
          return;
        }
        event.preventDefault();
        if (draggedEntryId !== null && draggedEntryId !== entryId) {
          const rect = dayCard.getBoundingClientRect();
          const offsetY = event.clientY - rect.top;
          const placement = offsetY > (rect.height / 2) ? "after" : "before";
          setDropTarget(entryId, placement);
        }
      });

      dayCard.addEventListener("drop", (event) => {
        if (isMealPlanOfflineReadOnly()) {
          return;
        }
        event.preventDefault();
        const sourceId = draggedEntryId;
        const placement = dayCard.classList.contains("is-drop-after") ? "after" : "before";
        clearDayDropTargets();
        draggedEntryId = null;
        detailNode.querySelectorAll(".wf-plan-day.is-dragging").forEach((node) => {
          node.classList.remove("is-dragging");
        });
        if (Number.isInteger(sourceId)) {
          queueReorderEntry(sourceId, entryId, placement);
        }
      });

      dayCard.addEventListener("dragend", () => {
        draggedEntryId = null;
        clearDayDropTargets();
        dayCard.classList.remove("is-dragging");
      });

      dayCard.addEventListener("touchstart", (event) => {
        if (isMealPlanOfflineReadOnly()) {
          return;
        }
        const target = event.target;
        if (!(target instanceof Element)) {
          return;
        }
        if (!target.closest('[data-role="drag-handle"]')) {
          return;
        }

        touchDraggedEntryId = entryId;
        touchDropEntryId = null;
        dayCard.classList.add("is-dragging");
      }, { passive: true });

      dayCard.addEventListener("touchmove", (event) => {
        if (isMealPlanOfflineReadOnly()) {
          return;
        }
        if (!Number.isInteger(touchDraggedEntryId)) {
          return;
        }

        const touch = event.changedTouches[0];
        if (!touch) {
          return;
        }

        const underPointer = document.elementFromPoint(touch.clientX, touch.clientY);
        if (!(underPointer instanceof Element)) {
          return;
        }

        const card = underPointer.closest(".wf-plan-day");
        if (!(card instanceof HTMLElement)) {
          return;
        }

        const targetId = Number(card.dataset.entryId);
        if (!Number.isInteger(targetId)) {
          return;
        }

        if (targetId !== touchDraggedEntryId) {
          touchDropEntryId = targetId;
          const rect = card.getBoundingClientRect();
          const offsetY = touch.clientY - rect.top;
          touchDropPlacement = offsetY > (rect.height / 2) ? "after" : "before";
          setDropTarget(targetId, touchDropPlacement);
        }

        event.preventDefault();
      }, { passive: false });

      dayCard.addEventListener("touchend", () => {
        if (isMealPlanOfflineReadOnly()) {
          return;
        }
        if (!Number.isInteger(touchDraggedEntryId)) {
          return;
        }

        const sourceId = touchDraggedEntryId;
        const targetId = touchDropEntryId;
        const placement = touchDropPlacement;

        touchDraggedEntryId = null;
        touchDropEntryId = null;
        touchDropPlacement = "before";
        clearDayDropTargets();
        dayCard.classList.remove("is-dragging");

        if (Number.isInteger(targetId)) {
          queueReorderEntry(sourceId, targetId, placement);
        }
      });

      dayCard.addEventListener("click", (event) => {
        if (consumeSuppressedDayCardClick(dayCard)) {
          return;
        }
        const target = event.target;
        if (!(target instanceof Element)) {
          return;
        }
        if (target.closest('[data-role="drag-handle"]')) {
          return;
        }
        void openMealEditor(entryId);
      });

      stack.appendChild(dayCard);
    }

    detailNode.appendChild(stack);
  }

  async function refreshPlans() {
    let plans = [];
    let listFromApi = false;

    try {
      const listPayload = await loadStoredMealPlans(reportApiReachable);
      assertRequiredFields(listPayload, ["data"], "Meal plan list response");
      const rawPlans = Array.isArray(listPayload.data) ? listPayload.data : [];
      plans = sortPlansMostRecentFirst(rawPlans);
      cachePlanListRows(plans);
      listFromApi = true;
    } catch {
      const cached = readMealPlanCache().list;
      plans = sortPlansMostRecentFirst(Array.isArray(cached) ? cached : []);
      if (plans.length > 0) {
        setStatus("Offline: showing cached meal plans.");
      } else {
        throw new Error("Unable to load meal plans while offline.");
      }
    }

    if (plans.length === 0) {
      activePlanId = null;
      selectedPlanId = null;
      writeActiveMealPlanId(null);
      renderPlanList(plans);
      renderPlanDetail(null);
      setAppTab("meal-plans");
      return;
    }

    const firstPlanId = Number(plans[0].plan_id);
    activePlanId = firstPlanId;

    const planIds = new Set(plans.map((row) => Number(row.plan_id)).filter((id) => Number.isInteger(id)));
    for (const cachedPlanId of Array.from(planPreviewTitlesById.keys())) {
      if (!planIds.has(cachedPlanId)) {
        planPreviewTitlesById.delete(cachedPlanId);
      }
    }

    if (Number.isInteger(firstPlanId) && !planPreviewTitlesById.has(firstPlanId)) {
      try {
        const activePayload = await loadMealPlan(firstPlanId, reportApiReachable);
        assertRequiredFields(activePayload, ["data"], "Meal plan detail response");
        cachePlanPreview(activePayload.data);
        cachePlanDetail(activePayload.data);
      } catch {
        const cached = cachedPlanDetail(firstPlanId);
        if (cached) {
          cachePlanPreview(cached);
        }
      }
    }

    if (Number.isInteger(selectedPlanId)) {
      const selectedStillExists = plans.some((row) => Number(row.plan_id) === selectedPlanId);
      if (!selectedStillExists) {
        selectedPlanId = null;
      }
    }

    if (Number.isInteger(selectedPlanId)) {
      writeActiveMealPlanId(selectedPlanId);
    } else if (Number.isInteger(firstPlanId)) {
      writeActiveMealPlanId(firstPlanId);
    }

    renderPlanList(plans);
    if (listFromApi) {
      updateMealPlanActionAvailability();
    }
  }

  async function reloadSelectedPlan() {
    if (!Number.isInteger(selectedPlanId)) {
      return;
    }

    writeActiveMealPlanId(selectedPlanId);

    let planData = null;
    try {
      const payload = await loadMealPlan(selectedPlanId, reportApiReachable);
      assertRequiredFields(payload, ["data"], "Meal plan detail response");
      planData = payload.data;
    } catch {
      planData = cachedPlanDetail(selectedPlanId);
      if (!planData) {
        throw new Error("Unable to load selected meal plan while offline.");
      }
      setStatus("Offline: showing cached meal plan.");
    }

    cachePlanPreview(planData);
    cachePlanDetail(planData);
    renderPlanDetail(selectedPlanDetail());

    let plans = [];
    try {
      const listPayload = await loadStoredMealPlans(reportApiReachable);
      const rawPlans = Array.isArray(listPayload.data) ? listPayload.data : [];
      plans = sortPlansMostRecentFirst(rawPlans);
      cachePlanListRows(plans);
    } catch {
      plans = sortPlansMostRecentFirst(readMealPlanCache().list);
    }
    renderPlanList(plans);
  }

  async function openPlanEditor(planId) {
    selectedPlanId = planId;
    writeActiveMealPlanId(planId);

    const cachedPlan = cachedPlanDetail(planId);
    let planData = cachedPlan;
    if (cachedPlan) {
      cachePlanPreview(cachedPlan);
      renderPlanDetail(cachedPlan);
      setAppTab("meal-plan-detail");
    }

    try {
      const payload = await loadMealPlan(planId, reportApiReachable);
      assertRequiredFields(payload, ["data"], "Meal plan detail response");
      planData = payload.data;
    } catch {
      if (!planData) {
        throw new Error("Unable to open this plan while offline.");
      }
      setStatus("Offline: opened cached meal plan.");
    }

    cachePlanPreview(planData);
    cachePlanDetail(planData);
    renderPlanDetail(selectedPlanDetail());
    setAppTab("meal-plan-detail");

    let plans = [];
    try {
      const listPayload = await loadStoredMealPlans(reportApiReachable);
      const rawPlans = Array.isArray(listPayload.data) ? listPayload.data : [];
      plans = sortPlansMostRecentFirst(rawPlans);
      cachePlanListRows(plans);
    } catch {
      plans = sortPlansMostRecentFirst(readMealPlanCache().list);
    }
    renderPlanList(plans);

    setStatus(`Loaded meal plan ${planDateRangeLabel(selectedPlanDetail())}.`);
  }

  async function generateShoppingList(mode = "sync") {
    assertMealPlanWriteAllowed("generate a shopping list from meal plans");
    if (!Number.isInteger(selectedPlanId)) {
      throw new Error("Select a meal plan first.");
    }
    if (generateShoppingInFlight) {
      return;
    }

    generateShoppingInFlight = true;

    generateShoppingButton.disabled = true;
    const initialText = generateShoppingButton.textContent;
    generateShoppingButton.textContent = mode === "regenerate_missing" ? "Re-generating..." : "Generating...";

    try {
      const payload = await generateMealPlanShoppingList(selectedPlanId, mode, reportApiReachable);
      assertRequiredFields(payload, ["data"], "Meal plan shopping response");

      const data = payload.data;
      const createdCount = Number.isInteger(Number(data.created_count))
        ? Number(data.created_count)
        : (data.created instanceof Array ? data.created.length : 0);
      const failedCount = Number.isInteger(Number(data.failed_count))
        ? Number(data.failed_count)
        : (data.failed instanceof Array ? data.failed.length : 0);
      if (mode === "regenerate_missing") {
        setStatus(`Shopping list regenerated: ${createdCount} updates, ${failedCount} failures.`);
      } else {
        setStatus(`Shopping list synced: ${createdCount} updates, ${failedCount} failures.`);
      }
    } finally {
      generateShoppingInFlight = false;
      generateShoppingButton.disabled = false;
      generateShoppingButton.textContent = initialText;
      setGenerateShoppingLongPressActive(false);
    }
  }

  function clearGenerateShoppingLongPressTimer() {
    if (generateShoppingLongPressTimer !== 0) {
      clearTimeout(generateShoppingLongPressTimer);
      generateShoppingLongPressTimer = 0;
    }
  }

  function startGenerateShoppingLongPress() {
    if (isMealPlanOfflineReadOnly()) {
      return;
    }
    if (generateShoppingInFlight) {
      return;
    }
    clearGenerateShoppingLongPressTimer();
    generateShoppingLongPressTriggered = false;
    generateShoppingSuppressClick = false;
    generateShoppingLongPressTimer = window.setTimeout(() => {
      generateShoppingLongPressTriggered = true;
      generateShoppingSuppressClick = true;
      generateShoppingLongPressTimer = 0;
      setGenerateShoppingLongPressActive(true);
      void runAction(async () => {
        await generateShoppingList("regenerate_missing");
      });
    }, GENERATE_SHOPPING_LONG_PRESS_MS);
  }

  function endGenerateShoppingLongPress() {
    clearGenerateShoppingLongPressTimer();
  }

  async function loadDefaultDinersForGenerateModal() {
    const payload = await loadMealPlanDefaultDiners(reportApiReachable);
    const data = payload.data;
    if (!data || typeof data !== "object") {
      throw new Error("User settings response is invalid.");
    }
    const defaultDiners = Number(data.default_diners);
    if (!Number.isInteger(defaultDiners)) {
      throw new Error("Configured default diners value is invalid.");
    }
    if (defaultDiners < 1 || defaultDiners > 20) {
      throw new Error("Configured default diners must be within 1..20.");
    }
    generateDinersInput.value = String(defaultDiners);
  }

  function openGenerateModal() {
    if (isMealPlanOfflineReadOnly()) {
      setStatus("Offline: meal plan generation is unavailable.");
      return;
    }
    generateStartDateInput.value = toIsoDate(new Date());
    generateLengthInput.value = "7";
    generateDinersInput.value = "2";
    generateModal.hidden = false;
    generateModalClosing = false;
    requestAnimationFrame(() => {
      generateModal.classList.add(generateSheetClass);
    });
    void runAction(loadDefaultDinersForGenerateModal);
  }

  function hideGenerateModalAfterTransition() {
    if (!generateModalClosing) {
      return;
    }
    generateModal.hidden = true;
    generateModalClosing = false;
  }

  function closeGenerateModal() {
    if (generateModal.hidden) {
      return;
    }

    generateModalClosing = true;
    generateModal.classList.remove(generateSheetClass);
    setTimeout(hideGenerateModalAfterTransition, 260);
  }

  function closeGenerateModalIfBackdrop(event) {
    if (event.target !== generateModal) {
      return;
    }
    closeGenerateModal();
  }

  function closeGenerateModalIfEscape(event) {
    if (event.key !== "Escape") {
      return;
    }
    closeGenerateModal();
  }

  function openStartDateModal() {
    if (isMealPlanOfflineReadOnly()) {
      setStatus("Offline: updating plan date is unavailable.");
      return;
    }
    const plan = selectedPlanDetail();
    if (!plan) {
      setStatus("Open a meal plan first.");
      return;
    }

    const current = String(plan.start_date || "").trim();
    startDateEditInput.value = current;
    startDateSaveButton.disabled = false;
    startDateCancelButton.disabled = false;
    startDateSaveButton.textContent = "Save";
    startDateModal.hidden = false;
  }

  function closeStartDateModal() {
    if (startDateModal.hidden) {
      return;
    }
    startDateModal.hidden = true;
  }

  function closeStartDateModalIfBackdrop(event) {
    if (event.target !== startDateModal) {
      return;
    }
    closeStartDateModal();
  }

  async function saveStartDate() {
    assertMealPlanWriteAllowed("update meal plan start date");
    if (!Number.isInteger(selectedPlanId)) {
      throw new Error("No meal plan selected.");
    }

    const startDate = startDateEditInput.value.trim();
    if (startDate.length === 0) {
      throw new Error("Start date is required.");
    }

    startDateSaveButton.disabled = true;
    startDateCancelButton.disabled = true;
    startDateSaveButton.textContent = "Saving...";

    try {
      await updateMealPlanStartDate(selectedPlanId, startDate, reportApiReachable);

      closeStartDateModal();
      await reloadSelectedPlan();
      setStatus(`Meal plan start date updated to ${startDate}.`);
      publishDataChanged();
    } finally {
      startDateSaveButton.disabled = false;
      startDateCancelButton.disabled = false;
      startDateSaveButton.textContent = "Save";
    }
  }

  function setGenerateSavingState(isSaving) {
    generateSaveButton.disabled = isSaving;
    generateCancelButton.disabled = isSaving;
    if (isSaving) {
      generateSaveButton.textContent = "Generating...";
      return;
    }
    generateSaveButton.textContent = "Generate";
  }

  async function generatePlan() {
    assertMealPlanWriteAllowed("generate a meal plan");
    setGenerateSavingState(true);

    try {
      const startDate = generateStartDateInput.value;
      if (startDate.trim().length === 0) {
        throw new Error("Start date is required.");
      }

      const lengthDays = Number(generateLengthInput.value);
      if (!Number.isInteger(lengthDays) || lengthDays < 1 || lengthDays > 31) {
        throw new Error("Duration must be an integer from 1 to 31.");
      }

      const diners = Number(generateDinersInput.value);
      if (!Number.isInteger(diners) || diners < 1 || diners > 20) {
        throw new Error("Diners must be an integer from 1 to 20.");
      }

      const payload = {
        start_date: startDate,
        length_days: lengthDays,
        diners,
        constraints: {
          leftover_days: [],
          takeout_days: [],
          empty_days: [],
        },
      };

      const result = await generateMealPlan(payload, reportApiReachable);

      const planData = result.data;
      const planId = Number(planData.plan_id);
      if (!Number.isInteger(planId)) {
        throw new Error("Server did not return a valid plan_id.");
      }

      selectedPlanId = planId;
      closeGenerateModal();

      await refreshPlans();
      await openPlanEditor(planId);
      setStatus(`Generated and opened meal plan ${planDateRangeLabel(planData)}.`);
      publishDataChanged();
    } finally {
      setGenerateSavingState(false);
    }
  }

  function firstEditorRecipe() {
    if (!Array.isArray(editorRecipes) || editorRecipes.length === 0) {
      return null;
    }
    const first = editorRecipes[0];
    if (!first || typeof first !== "object") {
      return null;
    }
    return first;
  }

  function recipePurposeDescription(purpose, index) {
    if (purpose === "shopping_only") {
      return "Shopping list only";
    }
    if (index === 0) {
      return "Part of tonight's meal";
    }
    return "Part of meal";
  }

  function syncMealTitleFromFirstRecipe() {
    if (editorMealTitleManuallySet) {
      return;
    }
    const first = firstEditorRecipe();
    if (first && typeof first.title === "string") {
      mealEditorNameInput.value = first.title;
      return;
    }
    mealEditorNameInput.value = "";
  }

  function updateRecipePurposePills(container, selectedPurpose) {
    const purposeButtons = Array.from(container.querySelectorAll("[data-purpose]"));
    for (const button of purposeButtons) {
      if (!(button instanceof HTMLButtonElement)) {
        continue;
      }
      const purpose = String(button.dataset.purpose);
      const selected = purpose === selectedPurpose;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-pressed", String(selected));
    }
  }

  function setAddRecipePurpose(purpose) {
    editorAddRecipePurpose = purpose === "shopping_only" ? "shopping_only" : "meal";
    updateRecipePurposePills(mealEditorRecipesPurpose, editorAddRecipePurpose);
  }

  function renderEditorRecipeCards() {
    mealEditorRecipesList.innerHTML = "";

    if (!Array.isArray(editorRecipes) || editorRecipes.length === 0) {
      return;
    }

    editorRecipes.forEach((recipe, index) => {
      const row = document.createElement("div");
      row.className = "wf-extra-row";

      const name = document.createElement("div");
      name.className = "wf-extra-row-name";
      const main = document.createElement("span");
      main.className = "wf-extra-row-name-main";
      main.textContent = String(recipe.title);
      const sub = document.createElement("small");
      sub.textContent = recipePurposeDescription(String(recipe.purpose || "meal"), index);
      name.appendChild(main);
      name.appendChild(sub);

      const purpose = document.createElement("div");
      purpose.className = "wf-extra-row-purpose";

      const mealButton = document.createElement("button");
      mealButton.className = "wf-pill-btn is-small";
      mealButton.type = "button";
      mealButton.textContent = "Meal";
      mealButton.dataset.purpose = "meal";

      const shoppingButton = document.createElement("button");
      shoppingButton.className = "wf-pill-btn is-small";
      shoppingButton.type = "button";
      shoppingButton.textContent = "Shopping only";
      shoppingButton.dataset.purpose = "shopping_only";

      purpose.appendChild(mealButton);
      purpose.appendChild(shoppingButton);

      const removeButton = document.createElement("button");
      removeButton.className = "wf-extra-remove-btn";
      removeButton.type = "button";
      removeButton.setAttribute("aria-label", "Remove recipe");
      removeButton.textContent = "x";

      const selectedPurpose = String(recipe.purpose || "meal");
      updateRecipePurposePills(purpose, selectedPurpose);

      mealButton.addEventListener("click", () => {
        editorRecipes[index].purpose = "meal";
        renderEditorRecipeCards();
      });

      shoppingButton.addEventListener("click", () => {
        editorRecipes[index].purpose = "shopping_only";
        renderEditorRecipeCards();
      });

      removeButton.addEventListener("click", () => {
        editorRecipes = editorRecipes.filter((_, recipeIndex) => recipeIndex !== index);
        renderEditorRecipeCards();
        syncMealTitleFromFirstRecipe();
      });

      row.appendChild(name);
      row.appendChild(purpose);
      row.appendChild(removeButton);
      mealEditorRecipesList.appendChild(row);
    });
  }

  function setEditorRecipes(recipes) {
    if (!Array.isArray(recipes)) {
      editorRecipes = [];
      renderEditorRecipeCards();
      syncMealTitleFromFirstRecipe();
      return;
    }

    const normalized = [];
    for (const recipe of recipes) {
      if (!recipe || typeof recipe !== "object") {
        continue;
      }
      const title = String(recipe.title || "").trim();
      if (title.length === 0) {
        continue;
      }

      const id = Number(recipe.id);
      const purpose = recipe.purpose === "shopping_only" ? "shopping_only" : "meal";
      normalized.push({
        title,
        purpose,
        id: Number.isInteger(id) ? id : null,
      });
    }

    editorRecipes = normalized;
    renderEditorRecipeCards();
    syncMealTitleFromFirstRecipe();
  }

  function setAddRecipeRowVisible(visible) {
    const show = Boolean(visible);
    mealEditorRecipesAddRow.hidden = !show;
    mealEditorRecipesSearchResults.hidden = !show;
    if (!show) {
      mealEditorRecipesSearchInput.value = "";
      mealEditorRecipesSearchResults.innerHTML = "";
      if (editorSearchTimer) {
        window.clearTimeout(editorSearchTimer);
        editorSearchTimer = 0;
      }
      setAddRecipePurpose("meal");
      return;
    }
    mealEditorRecipesSearchInput.focus();
  }

  function renderMealEditorSearchResults(results) {
    mealEditorRecipesSearchResults.innerHTML = "";

    if (!Array.isArray(results) || results.length === 0) {
      const empty = document.createElement("p");
      empty.className = "wf-meal-search-empty";
      empty.textContent = "No matching recipes.";
      mealEditorRecipesSearchResults.appendChild(empty);
      return;
    }

    for (const result of results) {
      const id = Number(result.id);
      if (!Number.isInteger(id)) {
        continue;
      }

      const title = String(result.title || "").trim();
      if (title.length === 0) {
        continue;
      }

      const button = document.createElement("button");
      button.className = "wf-meal-search-option";
      button.type = "button";
      button.textContent = title;
      button.addEventListener("click", () => {
        const existingIndex = editorRecipes.findIndex((row) => Number(row.id) === id);
        if (existingIndex >= 0) {
          editorRecipes[existingIndex].purpose = editorAddRecipePurpose;
        } else {
          editorRecipes.push({ id, title, purpose: editorAddRecipePurpose });
        }
        renderEditorRecipeCards();
        syncMealTitleFromFirstRecipe();
        setAddRecipeRowVisible(false);
      });
      mealEditorRecipesSearchResults.appendChild(button);
    }
  }

  function extractRecipeResults(payload) {
    const data = payload.data;

    if (Array.isArray(data)) {
      return data.map((item) => {
        let title = "";
        if (item && typeof item === "object") {
          if (typeof item.title === "string") {
            title = item.title;
          } else if (typeof item.name === "string") {
            title = item.name;
          }
        }
        return { id: item.id, title };
      });
    }

    if (data && typeof data === "object" && Array.isArray(data.results)) {
      return data.results.map((item) => {
        let title = "";
        if (item && typeof item === "object") {
          if (typeof item.title === "string") {
            title = item.title;
          } else if (typeof item.name === "string") {
            title = item.name;
          }
        }
        return { id: item.id, title };
      });
    }

    return [];
  }

  async function searchRecipesLive() {
    const query = mealEditorRecipesSearchInput.value.trim();

    if (mealEditorRecipesAddRow.hidden) {
      return;
    }

    if (query.length < 2) {
      mealEditorRecipesSearchResults.innerHTML = "";
      return;
    }

    const payload = await searchMealPlanRecipes(query, reportApiReachable);
    const results = extractRecipeResults(payload);
    renderMealEditorSearchResults(results);
  }

  function scheduleRecipeSearch() {
    if (editorSearchTimer) {
      window.clearTimeout(editorSearchTimer);
    }

    editorSearchTimer = window.setTimeout(() => {
      void runAction(searchRecipesLive);
    }, 220);
  }

  function setEditorMode(nextMode) {
    editorMode = nextMode;

    for (const button of mealEditorModes) {
      const mode = String(button.dataset.mode);
      const selected = mode === nextMode;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-pressed", String(selected));
    }

    const showMealField = nextMode === "planned" || nextMode === "takeout" || nextMode === "empty";
    const showRecipesField = nextMode === "planned";
    const showDinersField = nextMode === "planned" || nextMode === "leftover" || nextMode === "takeout";
    const showReminderField = nextMode === "planned" || nextMode === "leftover";

    mealEditorNameField.hidden = !showMealField;
    mealEditorRecipesField.hidden = !showRecipesField;
    mealEditorDinersField.hidden = !showDinersField;
    mealEditorReminderField.hidden = !showReminderField;

    mealEditorNameInput.disabled = !showMealField;

    if (!showRecipesField) {
      setAddRecipeRowVisible(false);
    }

    if (nextMode === "empty") {
      mealEditorNameInput.placeholder = "Where are you eating out?";
    } else if (nextMode === "takeout") {
      mealEditorNameInput.placeholder = "Takeout place";
    } else {
      mealEditorNameInput.placeholder = "";
    }
  }

  function setEditorServings(nextValue) {
    const clamped = Math.max(1, Math.min(20, nextValue));
    editorServings = clamped;
    mealEditorDinersValue.textContent = String(clamped);
  }

  function openMealEditorModal() {
    mealEditorModal.hidden = false;
    mealEditorClosing = false;
  }

  function closeMealEditorModal() {
    if (mealEditorModal.hidden) {
      return;
    }

    mealEditorClosing = true;
    mealEditorModal.hidden = true;
    mealEditorClosing = false;
    setAddRecipeRowVisible(false);
  }

  function closeMealEditorIfBackdrop(event) {
    if (event.target !== mealEditorModal) {
      return;
    }
    closeMealEditorModal();
  }

  function closeMealEditorIfEscape(event) {
    if (event.key !== "Escape") {
      return;
    }
    if (mealEditorModal.hidden) {
      return;
    }
    closeMealEditorModal();
  }

  async function openMealEditor(entryId) {
    const entry = findEntryById(entryId);
    if (!entry) {
      throw new Error("Meal day was not found.");
    }

    mealEditorEntryIdInput.value = String(entryId);

    editorMode = typeof entry.mode === "string" ? entry.mode : "planned";
    setEditorMode(editorMode);

    const servings = Number(entry.servings);
    setEditorServings(Number.isInteger(servings) ? servings : 2);

    const reminder = parseEntryReminder(entry);
    mealEditorReminderEnabled.checked = reminder.enabled;
    mealEditorReminderText.value = reminder.text;

    const title = entryRecipeTitle(entry);
    const baseRecipe = entry.recipe;
    const extraRecipes = Array.isArray(entry.extra_recipes) ? entry.extra_recipes : [];
    const recipeRows = [];

    if (baseRecipe && typeof baseRecipe === "object") {
      const baseTitle = String(baseRecipe.title || "").trim();
      const baseId = Number(baseRecipe.id);
      if (baseTitle.length > 0 || Number.isInteger(baseId)) {
        recipeRows.push({
          id: Number.isInteger(baseId) ? baseId : null,
          title: baseTitle.length > 0 ? baseTitle : "Untitled recipe",
          purpose: "meal",
        });
      }
    }

    for (const extraRecipe of extraRecipes) {
      if (!extraRecipe || typeof extraRecipe !== "object") {
        continue;
      }
      const recipe = extraRecipe.recipe;
      if (!recipe || typeof recipe !== "object") {
        continue;
      }
      const recipeTitle = String(recipe.title || "").trim();
      if (recipeTitle.length === 0) {
        continue;
      }
      const recipeId = Number(recipe.id);
      const purpose = extraRecipe.purpose === "shopping_only" ? "shopping_only" : "meal";
      recipeRows.push({
        id: Number.isInteger(recipeId) ? recipeId : null,
        title: recipeTitle,
        purpose,
      });
    }

    const normalizedTitle = title === "No recipe" ? "" : title;
    const firstRecipeTitle = recipeRows.length > 0 ? String(recipeRows[0].title) : "";
    editorMealTitleManuallySet = normalizedTitle.trim().length > 0 && normalizedTitle.trim() !== firstRecipeTitle.trim();
    mealEditorNameInput.value = normalizedTitle;
    setEditorRecipes(recipeRows);
    setAddRecipeRowVisible(false);

    openMealEditorModal();
    mealEditorSaveButton.disabled = isMealPlanOfflineReadOnly();
    if (isMealPlanOfflineReadOnly()) {
      setStatus("Offline: meal plan edits are disabled.");
    }
  }

  function toEditorRecipePayload(recipe) {
    const title = String(recipe.title || "").trim();
    if (title.length === 0) {
      return null;
    }
    const id = Number(recipe.id);
    if (Number.isInteger(id)) {
      return { id, title };
    }
    return { title };
  }

  function buildLegacyNotes(reminderEnabled, reminderText) {
    const payload = {
      reminder_enabled: reminderEnabled,
      reminder_text: reminderText,
    };
    return JSON.stringify(payload);
  }

  async function saveMealEditor() {
    assertMealPlanWriteAllowed("edit this meal day");
    if (!Number.isInteger(selectedPlanId)) {
      throw new Error("No meal plan selected.");
    }

    const entryId = Number(mealEditorEntryIdInput.value);
    if (!Number.isInteger(entryId)) {
      throw new Error("No meal day selected.");
    }

    mealEditorSaveButton.disabled = true;
    mealEditorCancelButton.disabled = true;
    mealEditorSaveButton.textContent = "Saving...";

    try {
      const reminderEnabled = mealEditorReminderEnabled.checked;
      const reminderText = mealEditorReminderText.value.trim();
      const mealTitle = mealEditorNameInput.value.trim();
      const primaryRecipe = editorRecipes.length > 0 ? toEditorRecipePayload(editorRecipes[0]) : null;
      const extraRecipes = editorRecipes.slice(1)
        .map((recipe) => {
          const payloadRecipe = toEditorRecipePayload(recipe);
          if (payloadRecipe === null) {
            return null;
          }
          return {
            purpose: recipe.purpose === "shopping_only" ? "shopping_only" : "meal",
            recipe: payloadRecipe,
          };
        })
        .filter((row) => row !== null);

      let recipePayload = null;
      if (editorMode === "planned") {
        recipePayload = primaryRecipe;
        if (recipePayload === null && mealTitle.length > 0) {
          recipePayload = { title: mealTitle };
        }
      }

      const patch = {
        mode: editorMode,
        servings: editorServings,
        recipe: recipePayload,
        extra_recipes: editorMode === "planned" ? extraRecipes : [],
        reminder_enabled: reminderEnabled,
        reminder_text: reminderText,
        notes: buildLegacyNotes(reminderEnabled, reminderText),
      };

      await updateMealPlanEntry(selectedPlanId, entryId, patch, reportApiReachable);

      closeMealEditorModal();
      await reloadSelectedPlan();
      setStatus("Meal day updated.");
      publishDataChanged();
    } finally {
      mealEditorSaveButton.disabled = false;
      mealEditorCancelButton.disabled = false;
      mealEditorSaveButton.textContent = "Save Changes";
    }
  }

  generateButton.addEventListener("click", openGenerateModal);
  generateCancelButton.addEventListener("click", closeGenerateModal);
  generateSaveButton.addEventListener("click", () => {
    void runAction(generatePlan);
  });
  changeStartDateButton.addEventListener("click", openStartDateModal);
  addDayButton.addEventListener("click", () => {
    void runAction(addMealDay);
  });
  generateShoppingButton.addEventListener("click", () => {
    if (generateShoppingSuppressClick || generateShoppingLongPressTriggered) {
      generateShoppingSuppressClick = false;
      generateShoppingLongPressTriggered = false;
      return;
    }
    void runAction(generateShoppingList);
  });
  generateShoppingButton.addEventListener("pointerdown", startGenerateShoppingLongPress);
  generateShoppingButton.addEventListener("pointerup", endGenerateShoppingLongPress);
  generateShoppingButton.addEventListener("pointerleave", endGenerateShoppingLongPress);
  generateShoppingButton.addEventListener("pointercancel", endGenerateShoppingLongPress);

  generateModal.addEventListener("click", closeGenerateModalIfBackdrop);
  startDateCancelButton.addEventListener("click", closeStartDateModal);
  startDateSaveButton.addEventListener("click", () => {
    void runAction(saveStartDate);
  });
  startDateModal.addEventListener("click", closeStartDateModalIfBackdrop);

  mealEditorCancelButton.addEventListener("click", closeMealEditorModal);
  mealEditorSaveButton.addEventListener("click", () => {
    void runAction(saveMealEditor);
  });
  mealEditorModal.addEventListener("click", closeMealEditorIfBackdrop);

  mealEditorDinersDown.addEventListener("click", () => {
    setEditorServings(editorServings - 1);
  });
  mealEditorDinersUp.addEventListener("click", () => {
    setEditorServings(editorServings + 1);
  });

  mealEditorRecipesSearchInput.addEventListener("input", scheduleRecipeSearch);
  mealEditorRecipesAddButton.addEventListener("click", () => {
    if (editorMode !== "planned") {
      return;
    }
    setAddRecipeRowVisible(true);
  });
  mealEditorRecipesAddCancel.addEventListener("click", () => {
    setAddRecipeRowVisible(false);
  });
  mealEditorRecipesPurpose.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) {
      return;
    }
    const purpose = String(target.dataset.purpose || "");
    setAddRecipePurpose(purpose);
  });
  mealEditorNameInput.addEventListener("input", () => {
    const first = firstEditorRecipe();
    const nextValue = mealEditorNameInput.value.trim();
    editorMealTitleManuallySet = first ? nextValue !== String(first.title).trim() : nextValue.length > 0;
  });

  for (const button of mealEditorModes) {
    button.addEventListener("click", () => {
      const mode = String(button.dataset.mode);
      setEditorMode(mode);
    });
  }

  window.addEventListener("keydown", (event) => {
    closeGenerateModalIfEscape(event);
    if (event.key === "Escape") {
      closeStartDateModal();
    }
    closeMealEditorIfEscape(event);
  });

  window.addEventListener("online", () => {
    updateMealPlanActionAvailability();
  });

  window.addEventListener("offline", () => {
    updateMealPlanActionAvailability();
  });

  window.addEventListener("wfd:online-state", () => {
    updateMealPlanActionAvailability();
    if (selectedPlanDetail()) {
      renderPlanDetail(selectedPlanDetail());
    }
  });

  window.addEventListener("wfd:open-meal-editor", (event) => {
    const detail = event instanceof CustomEvent ? event.detail : null;
    if (!detail || typeof detail !== "object") {
      return;
    }

    const planId = Number(detail.planId);
    const entryId = Number(detail.entryId);
    if (!Number.isInteger(planId) || !Number.isInteger(entryId)) {
      return;
    }

    void runAction(async () => {
      await openPlanEditor(planId);
      await openMealEditor(entryId);
    });
  });

  async function runAction(action) {
    const queuedAction = mealPlanActionQueue.then(action);
    mealPlanActionQueue = queuedAction.catch(() => {});

    try {
      await queuedAction;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStatus(message);
      window.alert("Meal plan sync failed. Retry the change or reload the meal plan to revert it.");
    }
  }

  setAppTab("meal-plans");
  updateMealPlanActionAvailability();
  //setStatus("Choose a meal plan to edit.");
  const cachedPlans = sortPlansMostRecentFirst(readMealPlanCache().list);
  renderPlanList(cachedPlans);
  void runAction(refreshPlans);
})();
