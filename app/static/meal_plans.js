(() => {
  const apiPrefix = window.WFD_API_PREFIX;

  const backButton = document.getElementById("wf-plan-back-btn");
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

  const mealEditorModal = document.getElementById("wf-meal-editor-modal");
  const mealEditorEntryIdInput = document.getElementById("wf-meal-editor-entry-id");
  const mealEditorNameInput = document.getElementById("wf-meal-editor-name");
  const mealEditorSearchInput = document.getElementById("wf-meal-editor-search");
  const mealEditorSearchResults = document.getElementById("wf-meal-editor-search-results");
  const mealEditorModes = Array.from(document.querySelectorAll("#wf-meal-editor-modes [data-mode]"));
  const mealEditorDinersDown = document.getElementById("wf-meal-editor-diners-down");
  const mealEditorDinersUp = document.getElementById("wf-meal-editor-diners-up");
  const mealEditorDinersValue = document.getElementById("wf-meal-editor-diners-value");
  const mealEditorReminderEnabled = document.getElementById("wf-meal-editor-reminder-enabled");
  const mealEditorReminderText = document.getElementById("wf-meal-editor-reminder-text");
  const mealEditorCancelButton = document.getElementById("wf-meal-editor-cancel");
  const mealEditorSaveButton = document.getElementById("wf-meal-editor-save");

  if (
    !(backButton instanceof HTMLButtonElement) ||
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
    !(mealEditorModal instanceof HTMLElement) ||
    !(mealEditorEntryIdInput instanceof HTMLInputElement) ||
    !(mealEditorNameInput instanceof HTMLInputElement) ||
    !(mealEditorSearchInput instanceof HTMLInputElement) ||
    !(mealEditorSearchResults instanceof HTMLElement) ||
    !(mealEditorDinersDown instanceof HTMLButtonElement) ||
    !(mealEditorDinersUp instanceof HTMLButtonElement) ||
    !(mealEditorDinersValue instanceof HTMLElement) ||
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
  let selectedPlan = null;
  let generateModalClosing = false;

  let editorSelectedRecipe = null;
  let editorMode = "planned";
  let editorServings = 2;
  let editorSearchTimer = 0;
  let mealEditorClosing = false;

  let draggedEntryId = null;
  let touchDraggedEntryId = null;
  let touchDropEntryId = null;
  let touchDropPlacement = "before";

  function setStatus(message) {
    statusNode.textContent = message;
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

  async function api(path, options) {
    let opts = {};
    if (options && typeof options === "object") {
      opts = options;
    }

    const response = await fetch(`${apiPrefix}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });

    const payload = await response.json();
    if (!response.ok) {
      if (typeof payload.detail === "string") {
        throw new Error(payload.detail);
      }
      throw new Error(JSON.stringify(payload));
    }

    return payload;
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

  function planMetaText(plan) {
    const lengthDays = Number(plan.length_days);
    const diners = Number(plan.diners);
    const entryCount = Number(plan.entry_count);
    const dayText = lengthDays === 1 ? "day" : "days";
    return `${lengthDays} ${dayText} • ${diners} diners • ${entryCount} entries`;
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
      return "Empty";
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
      heading.textContent = planDateRangeLabel(plan);
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

      const openHint = document.createElement("p");
      openHint.className = "wf-plan-card-open";
      openHint.textContent = "Open plan ›";

      card.appendChild(header);
      card.appendChild(meta);
      card.appendChild(openHint);

      card.addEventListener("click", () => {
        void runAction(() => openPlanEditor(planId));
      });

      listNode.appendChild(card);
    }
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
    if (!selectedPlan || typeof selectedPlan !== "object") {
      return null;
    }
    const entries = selectedPlan.entries;
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

  async function reorderEntry(dragEntryId, dropEntryId, dropPlacement = "before") {
    if (!Number.isInteger(selectedPlanId)) {
      return;
    }
    if (!selectedPlan || typeof selectedPlan !== "object") {
      return;
    }
    if (!Array.isArray(selectedPlan.entries)) {
      return;
    }
    if (!Number.isInteger(dragEntryId) || !Number.isInteger(dropEntryId)) {
      return;
    }
    if (dragEntryId === dropEntryId) {
      return;
    }

    const ordered = [...selectedPlan.entries].sort((a, b) => Number(a.day_index) - Number(b.day_index));

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

    await api(`/meal-plans/${selectedPlanId}/entries/${dragEntryId}`, {
      method: "PATCH",
      body: JSON.stringify({ target_day_index: targetDayIndex }),
    });

    await reloadSelectedPlan();
    setStatus("Meal day order updated.");
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
      dayCard.dataset.entryId = String(entryId);
      dayCard.draggable = true;

      const reminderBadge = reminder.enabled ? '<span class="wf-badge wf-badge-notify">🔔 Reminder Set</span>' : "";

      dayCard.innerHTML = `
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

      dayCard.addEventListener("dragstart", (event) => {
        draggedEntryId = entryId;
        dayCard.classList.add("is-dragging");
        if (event.dataTransfer) {
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", String(entryId));
        }
      });

      dayCard.addEventListener("dragover", (event) => {
        event.preventDefault();
        if (draggedEntryId !== null && draggedEntryId !== entryId) {
          const rect = dayCard.getBoundingClientRect();
          const offsetY = event.clientY - rect.top;
          const placement = offsetY > (rect.height / 2) ? "after" : "before";
          setDropTarget(entryId, placement);
        }
      });

      dayCard.addEventListener("drop", (event) => {
        event.preventDefault();
        const sourceId = draggedEntryId;
        const placement = dayCard.classList.contains("is-drop-after") ? "after" : "before";
        clearDayDropTargets();
        draggedEntryId = null;
        detailNode.querySelectorAll(".wf-plan-day.is-dragging").forEach((node) => {
          node.classList.remove("is-dragging");
        });
        if (Number.isInteger(sourceId)) {
          void runAction(() => reorderEntry(sourceId, entryId, placement));
        }
      });

      dayCard.addEventListener("dragend", () => {
        draggedEntryId = null;
        clearDayDropTargets();
        dayCard.classList.remove("is-dragging");
      });

      dayCard.addEventListener("touchstart", (event) => {
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
          void runAction(() => reorderEntry(sourceId, targetId, placement));
        }
      });

      dayCard.addEventListener("click", (event) => {
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
    const listPayload = await api("/meal-plans/stored");
    const rawPlans = Array.isArray(listPayload.data) ? listPayload.data : [];
    const plans = sortPlansMostRecentFirst(rawPlans);

    if (plans.length === 0) {
      activePlanId = null;
      selectedPlanId = null;
      selectedPlan = null;
      renderPlanList(plans);
      renderPlanDetail(null);
      setAppTab("meal-plans");
      return;
    }

    const firstPlanId = Number(plans[0].plan_id);
    activePlanId = firstPlanId;

    if (Number.isInteger(selectedPlanId)) {
      const selectedStillExists = plans.some((row) => Number(row.plan_id) === selectedPlanId);
      if (!selectedStillExists) {
        selectedPlanId = null;
        selectedPlan = null;
      }
    }

    renderPlanList(plans);
  }

  async function reloadSelectedPlan() {
    if (!Number.isInteger(selectedPlanId)) {
      return;
    }

    const payload = await api(`/meal-plans/${selectedPlanId}`);
    selectedPlan = payload.data;
    renderPlanDetail(selectedPlan);

    const listPayload = await api("/meal-plans/stored");
    const rawPlans = Array.isArray(listPayload.data) ? listPayload.data : [];
    const plans = sortPlansMostRecentFirst(rawPlans);
    renderPlanList(plans);
  }

  async function openPlanEditor(planId) {
    selectedPlanId = planId;

    const payload = await api(`/meal-plans/${planId}`);
    selectedPlan = payload.data;
    renderPlanDetail(selectedPlan);
    setAppTab("meal-plan-detail");

    const listPayload = await api("/meal-plans/stored");
    const rawPlans = Array.isArray(listPayload.data) ? listPayload.data : [];
    const plans = sortPlansMostRecentFirst(rawPlans);
    renderPlanList(plans);

    setStatus(`Loaded meal plan ${planDateRangeLabel(selectedPlan)}.`);
  }

  async function generateShoppingList() {
    if (!Number.isInteger(selectedPlanId)) {
      throw new Error("Select a meal plan first.");
    }

    generateShoppingButton.disabled = true;
    const initialText = generateShoppingButton.textContent;
    generateShoppingButton.textContent = "Generating...";

    try {
      const payload = await api(`/meal-plans/${selectedPlanId}/shopping-list`, {
        method: "POST",
      });

      const data = payload.data;
      const createdCount = Number(data.created_count);
      const failedCount = Number(data.failed_count);
      setStatus(`Shopping list synced: ${createdCount} updates, ${failedCount} failures.`);
    } finally {
      generateShoppingButton.disabled = false;
      generateShoppingButton.textContent = initialText;
    }
  }

  async function loadDefaultDinersForGenerateModal() {
    const payload = await api("/config/user-settings");
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

      const result = await api("/meal-plans/generate", {
        method: "POST",
        body: JSON.stringify(payload),
      });

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

  function backToPlanList() {
    setAppTab("meal-plans");
    selectedPlanId = null;
    selectedPlan = null;
    setStatus("Choose a meal plan to edit.");
  }

  function renderMealEditorSearchResults(results) {
    mealEditorSearchResults.innerHTML = "";

    if (!Array.isArray(results) || results.length === 0) {
      const empty = document.createElement("p");
      empty.className = "wf-meal-search-empty";
      empty.textContent = "No matching recipes.";
      mealEditorSearchResults.appendChild(empty);
      return;
    }

    for (const result of results) {
      const id = Number(result.id);
      if (!Number.isInteger(id)) {
        continue;
      }

      const title = String(result.title);
      const button = document.createElement("button");
      button.className = "wf-meal-search-option";
      button.type = "button";
      button.textContent = title;
      button.addEventListener("click", () => {
        editorSelectedRecipe = { id, title };
        mealEditorNameInput.value = title;
        mealEditorSearchResults.innerHTML = "";
      });
      mealEditorSearchResults.appendChild(button);
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
    const query = mealEditorSearchInput.value.trim();

    if (query.length < 2) {
      mealEditorSearchResults.innerHTML = "";
      return;
    }

    const payload = await api(`/recipes?search=${encodeURIComponent(query)}&limit=8`);
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

    const disableRecipeFields = nextMode === "empty";
    mealEditorNameInput.disabled = disableRecipeFields;
    mealEditorSearchInput.disabled = disableRecipeFields;

    if (disableRecipeFields) {
      mealEditorNameInput.value = "";
      mealEditorSearchInput.value = "";
      mealEditorSearchResults.innerHTML = "";
      editorSelectedRecipe = null;
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
    mealEditorSearchResults.innerHTML = "";
    mealEditorSearchInput.value = "";
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
    mealEditorNameInput.value = title === "No recipe" ? "" : title;

    const recipe = entry.recipe;
    if (recipe && typeof recipe === "object") {
      const recipeId = Number(recipe.id);
      const recipeTitle = typeof recipe.title === "string" ? recipe.title : "";
      if (Number.isInteger(recipeId) && recipeTitle.trim().length > 0) {
        editorSelectedRecipe = { id: recipeId, title: recipeTitle.trim() };
      } else {
        editorSelectedRecipe = null;
      }
    } else {
      editorSelectedRecipe = null;
    }

    openMealEditorModal();
  }

  function buildRecipePayloadFromEditor() {
    if (editorMode === "empty") {
      return null;
    }

    if (editorSelectedRecipe && Number.isInteger(editorSelectedRecipe.id)) {
      return {
        id: editorSelectedRecipe.id,
        title: editorSelectedRecipe.title,
      };
    }

    const rawName = mealEditorNameInput.value.trim();
    if (rawName.length === 0) {
      return null;
    }

    return {
      title: rawName,
    };
  }

  function buildLegacyNotes(reminderEnabled, reminderText) {
    const payload = {
      reminder_enabled: reminderEnabled,
      reminder_text: reminderText,
    };
    return JSON.stringify(payload);
  }

  async function saveMealEditor() {
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

      const patch = {
        mode: editorMode,
        servings: editorServings,
        recipe: buildRecipePayloadFromEditor(),
        reminder_enabled: reminderEnabled,
        reminder_text: reminderText,
        notes: buildLegacyNotes(reminderEnabled, reminderText),
      };

      await api(`/meal-plans/${selectedPlanId}/entries/${entryId}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });

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
  generateShoppingButton.addEventListener("click", () => {
    void runAction(generateShoppingList);
  });

  backButton.addEventListener("click", backToPlanList);
  generateModal.addEventListener("click", closeGenerateModalIfBackdrop);

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

  mealEditorSearchInput.addEventListener("input", scheduleRecipeSearch);
  mealEditorNameInput.addEventListener("input", () => {
    editorSelectedRecipe = null;
  });

  for (const button of mealEditorModes) {
    button.addEventListener("click", () => {
      const mode = String(button.dataset.mode);
      setEditorMode(mode);
    });
  }

  window.addEventListener("keydown", (event) => {
    closeGenerateModalIfEscape(event);
    closeMealEditorIfEscape(event);
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
    try {
      await action();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStatus(message);
    }
  }

  setAppTab("meal-plans");
  setStatus("Choose a meal plan to edit.");
  void runAction(refreshPlans);
})();
