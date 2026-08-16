(() => {
  const apiPrefix = window.WFD_API_PREFIX;
  const output = document.getElementById("output");
  const SHOPPING_MODE_CACHE_KEY = "wfd.shopping-mode.v1";
  const SHOPPING_STATUSES = new Set(["remaining", "skipped", "completed"]);

  let selectedPlanId = null;
  const shoppingModeState = {
    itemsById: {},
    pendingChanges: [],
    serverCursor: 0,
  };

  function show(data) {
    output.textContent = JSON.stringify(data, null, 2);
  }

  function parseCommaIntList(value) {
    return value
      .split(",")
      .map((raw) => raw.trim())
      .filter((raw) => raw.length > 0)
      .map((raw) => Number(raw))
      .filter((raw) => Number.isInteger(raw));
  }

  function escapeAttr(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("\"", "&quot;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  async function api(path, options = {}) {
    const res = await fetch(`${apiPrefix}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(JSON.stringify(data));
    }

    return data;
  }

  async function run(action) {
    try {
      await action();
    } catch (err) {
      output.textContent = `Request failed: ${err}`;
    }
  }

  function selectedKeywordIds() {
    const select = document.getElementById("cfg-tags");
    return Array.from(select.selectedOptions).map((opt) => Number(opt.value));
  }

  function renderSelectedKeywords(ids) {
    const target = document.getElementById("cfg-selected");
    target.innerHTML = "";
    if (!Array.isArray(ids) || ids.length === 0) {
      target.textContent = "No selected keywords saved yet.";
      return;
    }

    for (const id of ids) {
      const span = document.createElement("span");
      span.className = "pill";
      span.textContent = `#${id}`;
      target.appendChild(span);
    }
  }

  async function loadTags() {
    const payload = await api("/config/keywords");
    const items = Array.isArray(payload.data?.results)
      ? payload.data.results
      : Array.isArray(payload.data)
      ? payload.data
      : [];

    const select = document.getElementById("cfg-tags");
    select.innerHTML = "";

    for (const tag of items) {
      const opt = document.createElement("option");
      opt.value = String(tag.id);
      opt.textContent = tag.label || tag.name || `keyword-${tag.id}`;
      select.appendChild(opt);
    }

    show(payload);
  }

  async function loadSelectedKeywords() {
    const payload = await api("/config/keywords/selected");
    const selected = Array.isArray(payload.selected_keyword_ids)
      ? payload.selected_keyword_ids
      : [];

    const select = document.getElementById("cfg-tags");
    const selectedSet = new Set(selected.map((id) => Number(id)));
    for (const opt of select.options) {
      opt.selected = selectedSet.has(Number(opt.value));
    }

    renderSelectedKeywords(selected);
    show(payload);
  }

  async function saveSelectedKeywords() {
    const payload = await api("/config/keywords/selected", {
      method: "PUT",
      body: JSON.stringify({ keyword_ids: selectedKeywordIds() }),
    });

    renderSelectedKeywords(payload.selected_keyword_ids || []);
    show(payload);
  }

  async function loadPlanRules() {
    const payload = await api("/config/meal-plan-rules");
    const noRepeatDays = payload.data?.no_repeat_days;
    if (Number.isInteger(noRepeatDays) && noRepeatDays >= 0) {
      document.getElementById("cfg-no-repeat-days").value = String(noRepeatDays);
    }
    show(payload);
  }

  async function savePlanRules() {
    const value = Number(document.getElementById("cfg-no-repeat-days").value);
    if (!Number.isInteger(value) || value < 0) {
      throw new Error("No-repeat days must be an integer >= 0.");
    }

    const payload = await api("/config/meal-plan-rules", {
      method: "PUT",
      body: JSON.stringify({ no_repeat_days: value }),
    });
    show(payload);
  }

  async function runPanic() {
    const servings = Number(document.getElementById("panic-servings").value || 1);
    const noRepeatDays = Number(document.getElementById("cfg-no-repeat-days").value || 30);
    const startDate = new Date().toISOString().slice(0, 10);

    if (!Number.isInteger(servings) || servings < 1) {
      throw new Error("Servings must be an integer >= 1.");
    }

    if (!Number.isInteger(noRepeatDays) || noRepeatDays < 0) {
      throw new Error("No-repeat days must be an integer >= 0.");
    }

    const generation = await api("/meal-plans/generate", {
      method: "POST",
      body: JSON.stringify({
        start_date: startDate,
        length_days: 1,
        diners: servings,
        constraints: {
          leftover_days: [],
          takeout_days: [],
          empty_days: [],
        },
        no_repeat_days: noRepeatDays,
      }),
    });

    const planId = generation.data?.plan_id;
    if (!Number.isInteger(planId)) {
      throw new Error("Quick meal plan generation did not return a valid plan_id.");
    }

    setSelectedPlanId(planId);
    await selectPlan(planId);

    const shoppingGeneration = await api(`/meal-plans/${planId}/shopping-list`, {
      method: "POST",
    });

    const shoppingView = await refreshShoppingView();
    show({ generation, shoppingGeneration, shoppingView });
  }

  async function loadLastPanic() {
    const payload = await api("/meal-plans/stored");
    const plans = Array.isArray(payload.data) ? payload.data : [];
    if (plans.length === 0) {
      throw new Error("No stored meal plans found.");
    }

    const newestPlanId = Number(plans[0].plan_id);
    if (!Number.isInteger(newestPlanId) || newestPlanId < 1) {
      throw new Error("Newest stored meal plan has an invalid plan ID.");
    }

    await selectPlan(newestPlanId);
    show(payload);
  }

  function setSelectedPlanId(planId) {
    selectedPlanId = planId;
    const input = document.getElementById("plan-id");
    input.value = planId ? String(planId) : "";
  }

  function getSelectedPlanId() {
    const raw = Number(document.getElementById("plan-id").value);
    if (!Number.isInteger(raw) || raw < 1) {
      throw new Error("Valid selected plan ID is required.");
    }
    return raw;
  }

  function renderPlanEntries(entries) {
    const target = document.getElementById("plan-entries");
    target.innerHTML = "";

    if (!Array.isArray(entries) || entries.length === 0) {
      target.innerHTML = '<div class="muted">No entries for this plan.</div>';
      return;
    }

    const ordered = [...entries].sort((a, b) => Number(a.day_index) - Number(b.day_index));

    for (const entry of ordered) {
      const recipeTitle = entry.recipe?.title || "No recipe";
      const wrapper = document.createElement("div");
      wrapper.className = "item";

      const maxTargetDay = Math.max(ordered.length - 1, Number(entry.day_index) + 1);

      wrapper.innerHTML = `
        <div class="item-head">
          <strong>Day ${Number(entry.day_index) + 1}: ${recipeTitle}</strong>
          <span class="muted">Entry #${entry.entry_id} | ${entry.mode}</span>
        </div>
        <div class="muted">Date: ${entry.date} | Servings: ${entry.servings}</div>
        <div class="actions">
          <button data-action="pick-entry" data-entry-id="${entry.entry_id}" class="ghost">Use Entry</button>
          <button data-action="move-early" data-entry-id="${entry.entry_id}" data-day-index="${entry.day_index}" class="alt">Move Earlier</button>
          <button data-action="move-late" data-entry-id="${entry.entry_id}" data-day-index="${entry.day_index}" data-max-day="${maxTargetDay}" class="alt">Move Later</button>
          <button data-action="delete-entry" data-entry-id="${entry.entry_id}" class="danger">Delete Entry</button>
        </div>
      `;

      target.appendChild(wrapper);
    }

    target.querySelectorAll("button[data-action]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const action = btn.getAttribute("data-action");
        const entryId = Number(btn.getAttribute("data-entry-id"));
        const dayIndex = Number(btn.getAttribute("data-day-index"));
        const maxDay = Number(btn.getAttribute("data-max-day"));

        if (action === "pick-entry") {
          document.getElementById("plan-entry-id").value = String(entryId);
          return;
        }
        if (action === "move-early") {
          run(() => movePlanEntry(entryId, Math.max(0, dayIndex - 1)));
          return;
        }
        if (action === "move-late") {
          run(() => movePlanEntry(entryId, Math.max(0, dayIndex + 1), maxDay));
          return;
        }
        if (action === "delete-entry") {
          run(() => deletePlanEntry(entryId));
        }
      });
    });
  }

  function renderStoredPlans(plans) {
    const target = document.getElementById("plan-listbox");
    target.innerHTML = "";

    if (!Array.isArray(plans) || plans.length === 0) {
      target.innerHTML = '<div class="muted">No stored plans yet.</div>';
      setSelectedPlanId(null);
      renderPlanEntries([]);
      return;
    }

    for (const plan of plans) {
      const wrapper = document.createElement("div");
      const planId = Number(plan.plan_id);
      const activeClass = selectedPlanId === planId ? "item active" : "item";
      wrapper.className = activeClass;

      const keywords = Array.isArray(plan.keyword_ids) ? plan.keyword_ids.join(", ") : "";
      wrapper.innerHTML = `
        <div class="item-head">
          <strong>Plan #${planId}</strong>
          <span class="muted">${plan.length_days} days | ${plan.entry_count} entries</span>
        </div>
        <div class="muted">Start: ${plan.start_date} | Diners: ${plan.diners} | Keywords: ${keywords || "none"}</div>
        <div class="actions">
          <button data-action="select-plan" data-plan-id="${planId}" class="ghost">Select</button>
          <button data-action="delete-plan" data-plan-id="${planId}" class="danger">Delete</button>
        </div>
      `;
      target.appendChild(wrapper);
    }

    target.querySelectorAll("button[data-action]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const action = btn.getAttribute("data-action");
        const planId = Number(btn.getAttribute("data-plan-id"));

        if (action === "select-plan") {
          run(() => selectPlan(planId));
          return;
        }

        if (action === "delete-plan") {
          run(() => deleteStoredPlan(planId));
        }
      });
    });
  }

  async function listStoredPlans() {
    const payload = await api("/meal-plans/stored");
    renderStoredPlans(payload.data || []);
    show(payload);
  }

  async function selectPlan(planId) {
    setSelectedPlanId(planId);
    const payload = await api(`/meal-plans/${planId}`);
    renderPlanEntries(payload.data?.entries || []);
    await listStoredPlans();
    show(payload);
  }

  async function fetchPlan() {
    const planId = getSelectedPlanId();
    await selectPlan(planId);
  }

  async function deleteStoredPlan(planId) {
    const payload = await api(`/meal-plans/stored/${planId}`, {
      method: "DELETE",
    });

    if (selectedPlanId === planId) {
      setSelectedPlanId(null);
      renderPlanEntries([]);
    }

    await listStoredPlans();
    show(payload);
  }

  async function deleteSelectedPlan() {
    const planId = getSelectedPlanId();
    await deleteStoredPlan(planId);
  }

  async function generatePlan() {
    const startDate = document.getElementById("plan-start").value;
    if (!startDate) {
      throw new Error("Start date is required.");
    }

    const lengthDays = Number(document.getElementById("plan-length").value || 7);
    const diners = Number(document.getElementById("plan-diners").value || 2);
    const leftoverDays = parseCommaIntList(document.getElementById("plan-leftover").value);
    const takeoutDays = parseCommaIntList(document.getElementById("plan-takeout").value);
    const emptyDays = parseCommaIntList(document.getElementById("plan-empty").value);
    const noRepeatDays = Number(document.getElementById("cfg-no-repeat-days").value);
    if (!Number.isInteger(noRepeatDays) || noRepeatDays < 0) {
      throw new Error("No-repeat days must be an integer >= 0.");
    }

    const payload = await api("/meal-plans/generate", {
      method: "POST",
      body: JSON.stringify({
        start_date: startDate,
        length_days: lengthDays,
        diners,
        constraints: {
          leftover_days: leftoverDays,
          takeout_days: takeoutDays,
          empty_days: emptyDays,
        },
        no_repeat_days: noRepeatDays,
      }),
    });

    const planId = payload.data?.plan_id;
    if (planId) {
      setSelectedPlanId(planId);
      await selectPlan(planId);
    } else {
      await listStoredPlans();
    }

    show(payload);
  }

  async function movePlanEntry(entryIdArg, targetDayArg, maxDayArg) {
    const planId = getSelectedPlanId();
    const entryId =
      entryIdArg ?? Number(document.getElementById("plan-entry-id").value);

    const targetFromInput = Number(document.getElementById("plan-entry-day").value);
    let targetDay = targetDayArg ?? targetFromInput;

    if (!Number.isInteger(entryId) || entryId < 1) {
      throw new Error("Valid entry ID is required.");
    }

    if (!Number.isInteger(targetDay) || targetDay < 0) {
      throw new Error("Valid target day index is required.");
    }

    if (Number.isInteger(maxDayArg)) {
      targetDay = Math.min(targetDay, maxDayArg);
    }

    const payload = await api(`/meal-plans/${planId}/entries/${entryId}`, {
      method: "PATCH",
      body: JSON.stringify({ target_day_index: targetDay }),
    });

    document.getElementById("plan-entry-id").value = String(entryId);
    document.getElementById("plan-entry-day").value = String(targetDay);
    await selectPlan(planId);
    show(payload);
  }

  async function deletePlanEntry(entryIdArg) {
    const planId = getSelectedPlanId();
    const entryId =
      entryIdArg ?? Number(document.getElementById("plan-entry-id").value);

    if (!Number.isInteger(entryId) || entryId < 1) {
      throw new Error("Valid entry ID is required.");
    }

    const payload = await api(`/meal-plans/${planId}/entries/${entryId}`, {
      method: "DELETE",
    });

    await selectPlan(planId);
    show(payload);
  }

  function isOnline() {
    return navigator.onLine !== false;
  }

  function shoppingItemId(value) {
    const id = Number(value);
    return Number.isInteger(id) && id > 0 ? id : null;
  }

  function normalizeShoppingItem(item, fallbackStatus) {
    const id = shoppingItemId(item?.id);
    if (id === null) {
      return null;
    }

    const status = SHOPPING_STATUSES.has(item?.status) ? item.status : fallbackStatus;
    const unit = item?.unit ? String(item.unit) : "";
    return {
      id,
      name: String(item?.name || "Unnamed"),
      amount: item?.amount,
      unit,
      status: SHOPPING_STATUSES.has(status) ? status : "remaining",
      ingredient_type: String(item?.ingredient_type || "Other"),
      store_group: String(item?.store_group || "General"),
    };
  }

  function persistShoppingModeCache() {
    const payload = {
      itemsById: shoppingModeState.itemsById,
      pendingChanges: shoppingModeState.pendingChanges,
      serverCursor: shoppingModeState.serverCursor,
    };

    try {
      localStorage.setItem(SHOPPING_MODE_CACHE_KEY, JSON.stringify(payload));
    } catch {
      // Ignore storage write failures to keep the UI functional.
    }
  }

  function applyPendingStatusesToCache() {
    for (const change of shoppingModeState.pendingChanges) {
      if (!change || change.operation !== "update") {
        continue;
      }
      const entryId = shoppingItemId(change.entry_id);
      const status = change.payload?.status;
      if (entryId === null || !SHOPPING_STATUSES.has(status)) {
        continue;
      }
      const row = shoppingModeState.itemsById[String(entryId)];
      if (row) {
        row.status = status;
      }
    }
  }

  function loadShoppingModeCache() {
    try {
      const raw = localStorage.getItem(SHOPPING_MODE_CACHE_KEY);
      if (!raw) {
        return;
      }

      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") {
        if (parsed.itemsById && typeof parsed.itemsById === "object") {
          shoppingModeState.itemsById = parsed.itemsById;
        }
        if (Array.isArray(parsed.pendingChanges)) {
          shoppingModeState.pendingChanges = parsed.pendingChanges;
        }
        if (Number.isInteger(parsed.serverCursor)) {
          shoppingModeState.serverCursor = parsed.serverCursor;
        }
      }
    } catch {
      shoppingModeState.itemsById = {};
      shoppingModeState.pendingChanges = [];
      shoppingModeState.serverCursor = 0;
    }

    applyPendingStatusesToCache();
    persistShoppingModeCache();
  }

  function updateShoppingModeStatusBadges() {
    const networkNode = document.getElementById("shop-mode-network");
    const pendingNode = document.getElementById("shop-mode-pending");
    if (!networkNode || !pendingNode) {
      return;
    }

    networkNode.textContent = isOnline() ? "Status: online" : "Status: offline";
    pendingNode.textContent = `Pending sync: ${shoppingModeState.pendingChanges.length}`;
  }

  function sortedItemsByStatus(status) {
    return Object.values(shoppingModeState.itemsById)
      .filter((item) => item && item.status === status)
      .sort((a, b) => String(a.name).localeCompare(String(b.name)));
  }

  function createShopCard(item, mode) {
    const card = document.createElement("div");
    card.className = "shop-card";

    const unitPart = item.unit ? ` ${item.unit}` : "";
    const amountPart = item.amount ?? "";
    card.innerHTML = `
      <div class="shop-card-head">
        <strong>${escapeAttr(item.name)}</strong>
        <span class="muted">#${item.id}</span>
      </div>
      <div class="muted">${escapeAttr(String(amountPart))}${escapeAttr(unitPart)} | ${escapeAttr(item.ingredient_type)}</div>
    `;

    if (mode === "remaining") {
      attachRemainingCardGestures(card, item.id);
    } else {
      attachRestoreToRemainingClick(card, item.id);
    }

    return card;
  }

  function attachRemainingCardGestures(card, entryId) {
    let startX = 0;
    let startY = 0;
    let deltaX = 0;
    let isDragging = false;
    let suppressClick = false;

    card.addEventListener("touchstart", (event) => {
      const touch = event.changedTouches?.[0];
      if (!touch) {
        return;
      }
      startX = touch.clientX;
      startY = touch.clientY;
      deltaX = 0;
      isDragging = false;
      card.classList.remove("swiping");
    });

    card.addEventListener("touchmove", (event) => {
      const touch = event.changedTouches?.[0];
      if (!touch) {
        return;
      }

      deltaX = touch.clientX - startX;
      const deltaY = touch.clientY - startY;
      if (Math.abs(deltaX) <= Math.abs(deltaY)) {
        return;
      }

      isDragging = true;
      const clamped = Math.max(Math.min(deltaX, 0), -140);
      card.style.transform = `translateX(${clamped}px)`;
      card.classList.toggle("swiping", clamped < -20);
      if (event.cancelable) {
        event.preventDefault();
      }
    }, { passive: false });

    card.addEventListener("touchend", () => {
      const shouldSkip = isDragging && deltaX < -80;
      card.style.transform = "";
      card.classList.remove("swiping");

      if (shouldSkip) {
        suppressClick = true;
        run(() => setShoppingModeStatus(entryId, "skipped"));
      }

      isDragging = false;
      deltaX = 0;
    });

    card.addEventListener("click", () => {
      if (suppressClick) {
        suppressClick = false;
        return;
      }
      run(() => setShoppingModeStatus(entryId, "completed"));
    });
  }

  function attachRestoreToRemainingClick(card, entryId) {
    card.addEventListener("click", () => {
      run(() => setShoppingModeStatus(entryId, "remaining"));
    });
  }

  function renderShoppingModeSection(containerId, items, mode) {
    const container = document.getElementById(containerId);
    if (!container) {
      return;
    }
    container.innerHTML = "";

    if (!Array.isArray(items) || items.length === 0) {
      container.innerHTML = '<div class="shop-empty">No items.</div>';
      return;
    }

    for (const item of items) {
      container.appendChild(createShopCard(item, mode));
    }
  }

  function renderShoppingModeRemainingByCategory(items) {
    const container = document.getElementById("shop-mode-remaining");
    if (!container) {
      return;
    }
    container.innerHTML = "";

    if (!Array.isArray(items) || items.length === 0) {
      container.innerHTML = '<div class="shop-empty">No items.</div>';
      return;
    }

    const grouped = {};
    for (const item of items) {
      const key = String(item.ingredient_type || "Other");
      if (!grouped[key]) {
        grouped[key] = [];
      }
      grouped[key].push(item);
    }

    const categories = Object.keys(grouped).sort((a, b) => a.localeCompare(b));
    for (const category of categories) {
      const group = document.createElement("section");
      group.className = "shop-category";

      const title = document.createElement("div");
      title.className = "shop-category-title";
      title.textContent = category;
      group.appendChild(title);

      grouped[category]
        .sort((a, b) => String(a.name).localeCompare(String(b.name)))
        .forEach((item) => group.appendChild(createShopCard(item, "remaining")));

      container.appendChild(group);
    }
  }

  function renderShoppingMode() {
    const remaining = sortedItemsByStatus("remaining");
    const skipped = sortedItemsByStatus("skipped");
    const completed = sortedItemsByStatus("completed");

    renderShoppingModeRemainingByCategory(remaining);
    renderShoppingModeSection("shop-mode-skipped", skipped, "skipped");
    renderShoppingModeSection("shop-mode-completed", completed, "completed");
    updateShoppingModeStatusBadges();
  }

  function hydrateShoppingModeFromServer(payload) {
    const sections = payload?.data?.sections || {};
    const merged = {};

    for (const status of ["remaining", "skipped", "completed"]) {
      const list = Array.isArray(sections[status]) ? sections[status] : [];
      for (const item of list) {
        const normalized = normalizeShoppingItem(item, status);
        if (!normalized) {
          continue;
        }
        merged[String(normalized.id)] = normalized;
      }
    }

    shoppingModeState.itemsById = merged;
    if (Number.isInteger(payload?.cursor)) {
      shoppingModeState.serverCursor = payload.cursor;
    }

    applyPendingStatusesToCache();
    persistShoppingModeCache();
  }

  function queueStatusChange(entryId, status) {
    const parsedId = shoppingItemId(entryId);
    if (parsedId === null || !SHOPPING_STATUSES.has(status)) {
      return;
    }

    shoppingModeState.pendingChanges = shoppingModeState.pendingChanges.filter((change) => {
      return !(change?.operation === "update" && shoppingItemId(change.entry_id) === parsedId);
    });

    shoppingModeState.pendingChanges.push({
      operation: "update",
      entry_id: parsedId,
      payload: { status },
      queued_at: new Date().toISOString(),
    });

    const row = shoppingModeState.itemsById[String(parsedId)];
    if (row) {
      row.status = status;
    }

    persistShoppingModeCache();
  }

  async function syncShoppingModePending(showPayload = true) {
    updateShoppingModeStatusBadges();
    if (shoppingModeState.pendingChanges.length === 0) {
      return { source: "local-cache", applied: [], rejected: [] };
    }

    if (!isOnline()) {
      return {
        source: "local-cache",
        message: "Offline. Pending changes are kept locally.",
        pending_count: shoppingModeState.pendingChanges.length,
      };
    }

    const outgoing = [...shoppingModeState.pendingChanges];
    const payload = await api("/shopping-list/sync", {
      method: "POST",
      body: JSON.stringify({ changes: outgoing }),
    });

    const rejectedIndexes = new Set(
      (Array.isArray(payload.rejected) ? payload.rejected : [])
        .map((row) => Number(row?.index))
        .filter((value) => Number.isInteger(value) && value >= 0)
    );

    shoppingModeState.pendingChanges = outgoing.filter((_, idx) => rejectedIndexes.has(idx));
    if (Number.isInteger(payload.server_cursor)) {
      shoppingModeState.serverCursor = payload.server_cursor;
      document.getElementById("sync-cursor").value = String(payload.server_cursor);
    }

    persistShoppingModeCache();

    try {
      await refreshShoppingView();
    } catch {
      // Keep local view if server refresh fails after sync.
      renderShoppingMode();
      updateShoppingModeStatusBadges();
    }

    if (showPayload) {
      show(payload);
    }

    return payload;
  }

  async function setShoppingModeStatus(entryId, status) {
    if (!SHOPPING_STATUSES.has(status)) {
      throw new Error("Invalid status for shopping mode.");
    }

    queueStatusChange(entryId, status);
    renderShoppingMode();

    if (!isOnline()) {
      show({
        source: "local-cache",
        message: "Offline mode: change saved locally and queued for sync.",
        entry_id: entryId,
        status,
      });
      return;
    }

    await syncShoppingModePending(false);
    show({
      source: "shopping-mode",
      message: "Change synced to server.",
      entry_id: entryId,
      status,
      pending_count: shoppingModeState.pendingChanges.length,
    });
  }

  function renderShoppingSection(containerId, items, sectionName) {
    const container = document.getElementById(containerId);
    container.innerHTML = "";

    if (!Array.isArray(items) || items.length === 0) {
      container.innerHTML = '<div class="muted">No items.</div>';
      return;
    }

    for (const item of items) {
      const unitPart = item.unit ? ` ${item.unit}` : "";
      const amountPart = item.amount ?? "";
      const wrapper = document.createElement("div");
      wrapper.className = "item";

      wrapper.innerHTML = `
        <div class="item-head">
          <strong>${item.name}</strong>
          <span class="muted">Entry #${item.id}</span>
        </div>
        <div class="muted">${amountPart}${unitPart} | Type: ${item.ingredient_type} | Store: ${item.store_group}</div>
        <div class="actions">
          <button data-action="remaining" data-entry-id="${item.id}" class="ghost">Remaining</button>
          <button data-action="skipped" data-entry-id="${item.id}" class="alt">Skipped</button>
          <button data-action="completed" data-entry-id="${item.id}" class="alt">Completed</button>
          <button data-action="delete" data-entry-id="${item.id}" class="danger">Delete</button>
        </div>
        <div class="row" style="margin-top:0.4rem;">
          <input id="shop-edit-name-${item.id}" type="text" value="${escapeAttr(item.name)}" placeholder="Food name" />
          <input id="shop-edit-amount-${item.id}" type="number" step="0.01" value="${escapeAttr(item.amount ?? "")}" placeholder="Amount" />
          <button data-action="save-edit" data-entry-id="${item.id}">Save Edit</button>
        </div>
      `;

      container.appendChild(wrapper);
    }

    container.querySelectorAll("button[data-action]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const action = btn.getAttribute("data-action");
        const entryId = Number(btn.getAttribute("data-entry-id"));

        if (action === "delete") {
          run(() => deleteShoppingItem(entryId));
          return;
        }

        if (action === "save-edit") {
          run(() => updateShoppingItem(entryId));
          return;
        }

        if (action && action !== sectionName) {
          run(() => updateShoppingStatus(entryId, action));
        }
      });
    });
  }

  function renderShoppingViewPayload(payload) {
    const sections = payload.data?.sections || {};
    renderShoppingSection("shop-remaining", sections.remaining || [], "remaining");
    renderShoppingSection("shop-skipped", sections.skipped || [], "skipped");
    renderShoppingSection("shop-completed", sections.completed || [], "completed");
    hydrateShoppingModeFromServer(payload);
    renderShoppingMode();
  }

  async function refreshShoppingView() {
    const payload = await api("/shopping-list/view");
    renderShoppingViewPayload(payload);

    if (Number.isInteger(payload.cursor)) {
      document.getElementById("sync-cursor").value = String(payload.cursor);
    }

    show(payload);
    return payload;
  }

  async function addShoppingItem() {
    const name = document.getElementById("shop-name").value.trim();
    const amount = Number(document.getElementById("shop-amount").value || 1);

    if (!name) {
      throw new Error("Food name is required.");
    }

    const payload = await api("/shopping-list/entries", {
      method: "POST",
      body: JSON.stringify({
        food: { name },
        amount,
      }),
    });

    await refreshShoppingView();
    show(payload);
  }

  async function updateShoppingStatus(entryId, status) {
    if (!isOnline()) {
      queueStatusChange(entryId, status);
      renderShoppingMode();
      show({
        source: "local-cache",
        message: "Offline mode: update queued for sync.",
        entry_id: entryId,
        status,
      });
      return;
    }

    try {
      const payload = await api(`/shopping-list/entries/${entryId}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });

      await refreshShoppingView();
      show(payload);
    } catch (err) {
      queueStatusChange(entryId, status);
      renderShoppingMode();
      show({
        source: "local-cache",
        message: "Direct update failed, queued for sync.",
        error: String(err),
        entry_id: entryId,
        status,
      });
    }
  }

  async function deleteShoppingItem(entryId) {
    const payload = await api(`/shopping-list/entries/${entryId}`, {
      method: "DELETE",
    });

    await refreshShoppingView();
    show(payload);
  }

  async function updateShoppingItem(entryId) {
    const nameInput = document.getElementById(`shop-edit-name-${entryId}`);
    const amountInput = document.getElementById(`shop-edit-amount-${entryId}`);

    if (!nameInput || !amountInput) {
      throw new Error(`Could not find edit inputs for entry ${entryId}.`);
    }

    const name = nameInput.value.trim();
    const amount = Number(amountInput.value);

    if (!name) {
      throw new Error("Food name is required.");
    }

    if (!Number.isFinite(amount)) {
      throw new Error("Amount must be a valid number.");
    }

    const payload = await api(`/shopping-list/entries/${entryId}`, {
      method: "PATCH",
      body: JSON.stringify({
        food: { name },
        amount,
      }),
    });

    await refreshShoppingView();
    show(payload);
  }

  async function generatePlanShopping() {
    const planId = getSelectedPlanId();
    const generation = await api(`/meal-plans/${planId}/shopping-list`, {
      method: "POST",
    });

    const shoppingView = await refreshShoppingView();
    show({ generation, shoppingView });
  }

  async function pullSyncChanges() {
    const cursor = Number(document.getElementById("sync-cursor").value || 0);
    const payload = await api(`/shopping-list/sync?since=${cursor}`);
    if (Number.isInteger(payload.server_cursor)) {
      document.getElementById("sync-cursor").value = String(payload.server_cursor);
    }

    await refreshShoppingView();
    show(payload);
  }

  document.getElementById("cfg-load-tags").addEventListener("click", () => run(loadTags));
  document
    .getElementById("cfg-load-selected")
    .addEventListener("click", () => run(loadSelectedKeywords));
  document
    .getElementById("cfg-save-selected")
    .addEventListener("click", () => run(saveSelectedKeywords));
  document.getElementById("cfg-load-rules").addEventListener("click", () => run(loadPlanRules));
  document.getElementById("cfg-save-rules").addEventListener("click", () => run(savePlanRules));

  document.getElementById("panic-run").addEventListener("click", () => run(runPanic));
  document.getElementById("panic-last").addEventListener("click", () => run(loadLastPanic));

  document.getElementById("plan-generate").addEventListener("click", () => run(generatePlan));
  document.getElementById("plan-list").addEventListener("click", () => run(listStoredPlans));
  document.getElementById("plan-fetch").addEventListener("click", () => run(fetchPlan));
  document.getElementById("plan-shopping").addEventListener("click", () => run(generatePlanShopping));
  document.getElementById("plan-move-entry").addEventListener("click", () => run(() => movePlanEntry()));
  document.getElementById("plan-delete-entry").addEventListener("click", () => run(() => deletePlanEntry()));
  document.getElementById("plan-delete").addEventListener("click", () => run(deleteSelectedPlan));

  document.getElementById("shop-refresh").addEventListener("click", () => run(refreshShoppingView));
  document.getElementById("shop-add").addEventListener("click", () => run(addShoppingItem));
  document.getElementById("sync-pull").addEventListener("click", () => run(pullSyncChanges));
  const shoppingModeRefreshButton = document.getElementById("shop-mode-refresh");
  if (shoppingModeRefreshButton) {
    shoppingModeRefreshButton.addEventListener("click", () => run(refreshShoppingView));
  }
  const shoppingModeSyncButton = document.getElementById("shop-mode-sync");
  if (shoppingModeSyncButton) {
    shoppingModeSyncButton.addEventListener("click", () => run(() => syncShoppingModePending(true)));
  }

  window.addEventListener("online", () => {
    updateShoppingModeStatusBadges();
    run(() => syncShoppingModePending(false));
  });
  window.addEventListener("offline", () => {
    updateShoppingModeStatusBadges();
    show({
      source: "local-cache",
      message: "Offline mode enabled. Shopping updates will be queued.",
      pending_count: shoppingModeState.pendingChanges.length,
    });
  });

  const today = new Date().toISOString().slice(0, 10);
  document.getElementById("plan-start").value = today;

  loadShoppingModeCache();
  renderShoppingMode();

  run(async () => {
    await loadTags();
    await loadSelectedKeywords();
    await loadPlanRules();
    await listStoredPlans();
    await refreshShoppingView();
    if (shoppingModeState.pendingChanges.length > 0) {
      await syncShoppingModePending(false);
    }
  });
})();
