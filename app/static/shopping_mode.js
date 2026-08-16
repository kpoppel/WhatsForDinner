(() => {
  const DEBUG_MODE = false;

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/shopping-sw.js", { scope: "/" }).catch(() => {
        // Ignore service worker registration failures.
      });
    });

    // Reload once when a new service worker takes control (new build deployed).
    let _swRefreshing = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (!_swRefreshing) {
        _swRefreshing = true;
        window.location.reload();
      }
    });
  }

  // Pull-to-refresh: blocks native PTR when offline; triggers list refresh when online.
  let _ptrStartY = 0;
  let _ptrDragging = false;
  let _ptrIndicator = null;
  const PTR_THRESHOLD = 80;

  function getPtrIndicator() {
    if (!_ptrIndicator) {
      _ptrIndicator = document.createElement("div");
      _ptrIndicator.id = "ptr-indicator";
      _ptrIndicator.setAttribute("aria-hidden", "true");
      document.body.prepend(_ptrIndicator);
    }
    return _ptrIndicator;
  }

  document.addEventListener("touchstart", (e) => {
    _ptrStartY = e.touches[0].pageY;
    _ptrDragging = false;
  }, { passive: true });

  document.addEventListener("touchmove", (e) => {
    const dy = e.touches[0].pageY - _ptrStartY;
    if (dy <= 0 || window.scrollY !== 0) {
      return;
    }
    // Always prevent native PTR; we handle it ourselves when online.
    if (e.cancelable) {
      e.preventDefault();
    }
    if (!isOnline()) {
      return;
    }
    _ptrDragging = true;
    const indicator = getPtrIndicator();
    indicator.style.display = "flex";
    indicator.classList.toggle("ptr-ready", dy >= PTR_THRESHOLD);
  }, { passive: false });

  document.addEventListener("touchend", () => {
    if (!_ptrDragging || !_ptrIndicator) {
      return;
    }
    const wasReady = _ptrIndicator.classList.contains("ptr-ready");
    _ptrIndicator.classList.remove("ptr-ready");
    _ptrIndicator.style.display = "none";
    _ptrDragging = false;
    if (wasReady) {
      run(() => refreshAndSyncIfNeeded());
    }
  }, { passive: true });

  const apiPrefix = window.WFD_API_PREFIX;
  const output = document.getElementById("output");
  const CACHE_KEY = "wfd.shopping-mode.v1";
  const SHOPPING_STATUSES = new Set(["remaining", "skipped", "completed"]);
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

  const state = {
    itemsById: {},
    pendingChanges: [],
    serverCursor: 0,
    apiReachable: true,
    collapsedSections: {
      skipped: true,
      completed: true,
    },
  };

  function show(data) {
    if (DEBUG_MODE) {
      output.textContent = JSON.stringify(data, null, 2);
    }
  }

  function browserOnline() {
    return navigator.onLine !== false;
  }

  function isOnline() {
    return browserOnline() && state.apiReachable;
  }

  function setApiReachable(value) {
    state.apiReachable = Boolean(value);
    updateStatusBadges();
  }

  function escapeAttr(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("\"", "&quot;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  function shoppingItemId(value) {
    const id = Number(value);
    return Number.isInteger(id) && id > 0 ? id : null;
  }

  async function api(path, options = {}) {
    try {
      const response = await fetch(`${apiPrefix}${path}`, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(JSON.stringify(data));
      }

      setApiReachable(true);
      return data;
    } catch (error) {
      setApiReachable(false);
      throw error;
    }
  }

  async function run(action) {
    try {
      await action();
    } catch (err) {
      show({ message: "Request failed", status: `Error: ${err}` });
    }
  }


  function persistCache() {
    try {
      localStorage.setItem(CACHE_KEY, JSON.stringify(state));
    } catch {
      // Ignore write failures.
    }
  }

  function applyPendingChanges() {
    for (const change of state.pendingChanges) {
      if (!change) {
        continue;
      }

      const id = shoppingItemId(change.entry_id);
      if (id === null) {
        continue;
      }

      if (change.operation === "delete") {
        delete state.itemsById[String(id)];
        continue;
      }

      if (change.operation === "update") {
        const status = change.payload?.status;
        if (!SHOPPING_STATUSES.has(status)) {
          continue;
        }
        const row = state.itemsById[String(id)];
        if (row) {
          row.status = status;
        }
      }
    }
  }

  function loadCache() {
    try {
      const raw = localStorage.getItem(CACHE_KEY);
      if (!raw) {
        return;
      }
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") {
        if (parsed.itemsById && typeof parsed.itemsById === "object") {
          state.itemsById = parsed.itemsById;
        }
        if (Array.isArray(parsed.pendingChanges)) {
          state.pendingChanges = parsed.pendingChanges;
        }
        if (Number.isInteger(parsed.serverCursor)) {
          state.serverCursor = parsed.serverCursor;
        }
      }
    } catch {
      state.itemsById = {};
      state.pendingChanges = [];
      state.serverCursor = 0;
    }

    applyPendingChanges();
    persistCache();
  }

  function updateStatusBadges() {
    const network = document.getElementById("shop-mode-network");
    const pending = document.getElementById("shop-mode-pending");
    const pendingCount = document.getElementById("shop-mode-pending-count");
    const online = isOnline();

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

  function sortedByStatus(status) {
    return Object.values(state.itemsById)
      .filter((item) => item && item.status === status)
      .sort((a, b) => String(a.name).localeCompare(String(b.name)));
  }

  function suppressNextCardClick(card) {
    card.dataset.suppressNextClick = "1";
  }

  function consumeSuppressedCardClick(card) {
    if (card.dataset.suppressNextClick === "1") {
      card.dataset.suppressNextClick = "0";
      return true;
    }
    return false;
  }

  function attachSwipeRightDeleteGesture(card, entryId) {
    let startX = 0;
    let startY = 0;
    let deltaX = 0;
    let isDragging = false;

    card.addEventListener("touchstart", (event) => {
      const touch = event.changedTouches?.[0];
      if (!touch) {
        return;
      }
      startX = touch.clientX;
      startY = touch.clientY;
      deltaX = 0;
      isDragging = false;
      card.classList.remove("swiping-delete-right");
      card.style.setProperty("--swipe-delete-right-progress", "0");
    });

    card.addEventListener("touchmove", (event) => {
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
      const clamped = Math.max(Math.min(deltaX, 140), 0);
      card.style.transform = `translateX(${clamped}px)`;
      card.classList.toggle("swiping-delete-right", clamped > 20);
      const progress = Math.min(Math.abs(clamped) / 140, 1);
      card.style.setProperty("--swipe-delete-right-progress", String(progress));
      if (event.cancelable) {
        event.preventDefault();
      }
    }, { passive: false });

    card.addEventListener("touchend", () => {
      const shouldDelete = isDragging && deltaX > 80;
      card.style.transform = "";
      card.classList.remove("swiping-delete-right");
      card.style.setProperty("--swipe-delete-right-progress", "0");

      if (shouldDelete) {
        suppressNextCardClick(card);
        run(() => deleteEntry(entryId));
      }

      isDragging = false;
      deltaX = 0;
    });

    card.addEventListener("click", (event) => {
      if (consumeSuppressedCardClick(card)) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    }, true);
  }

  function attachRestoreToRemainingClick(card, entryId) {
    card.addEventListener("click", () => {
      if (consumeSuppressedCardClick(card)) {
        return;
      }
      run(() => setStatus(entryId, "remaining"));
    });
  }

  function attachRemainingCardGestures(card, entryId) {
    let startX = 0;
    let startY = 0;
    let deltaX = 0;
    let isDragging = false;

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
      card.style.setProperty("--swipe-skip-progress", "0");
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
      const progress = Math.min(Math.abs(clamped) / 140, 1);
      card.style.setProperty("--swipe-skip-progress", String(progress));
      if (event.cancelable) {
        event.preventDefault();
      }
    }, { passive: false });

    card.addEventListener("touchend", () => {
      const shouldSkip = isDragging && deltaX < -80;
      card.style.transform = "";
      card.classList.remove("swiping");
      card.style.setProperty("--swipe-skip-progress", "0");

      if (shouldSkip) {
        suppressNextCardClick(card);
        run(() => setStatus(entryId, "skipped"));
      }

      isDragging = false;
      deltaX = 0;
    });

    card.addEventListener("click", () => {
      if (consumeSuppressedCardClick(card)) {
        return;
      }
      run(() => setStatus(entryId, "completed"));
    });
  }

  function attachCompletedCardGestures(card, entryId) {
    let startX = 0;
    let startY = 0;
    let deltaX = 0;
    let isDragging = false;

    card.addEventListener("touchstart", (event) => {
      const touch = event.changedTouches?.[0];
      if (!touch) {
        return;
      }
      startX = touch.clientX;
      startY = touch.clientY;
      deltaX = 0;
      isDragging = false;
      card.classList.remove("swiping-delete");
      card.style.setProperty("--swipe-delete-progress", "0");
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
      card.classList.toggle("swiping-delete", clamped < -20);
      const progress = Math.min(Math.abs(clamped) / 140, 1);
      card.style.setProperty("--swipe-delete-progress", String(progress));
      if (event.cancelable) {
        event.preventDefault();
      }
    }, { passive: false });

    card.addEventListener("touchend", () => {
      const shouldDelete = isDragging && deltaX < -80;
      card.style.transform = "";
      card.classList.remove("swiping-delete");
      card.style.setProperty("--swipe-delete-progress", "0");

      if (shouldDelete) {
        suppressNextCardClick(card);
        run(() => deleteEntry(entryId));
      }

      isDragging = false;
      deltaX = 0;
    });

    card.addEventListener("click", () => {
      if (consumeSuppressedCardClick(card)) {
        return;
      }
      run(() => setStatus(entryId, "remaining"));
    });
  }

  function titleWithCount(label, count, collapsed) {
    if (typeof collapsed === "boolean") {
      return `${label} (${count}) ${collapsed ? "▸" : "▾"}`;
    }
    return `${label} (${count})`;
  }

  function updateSectionTitle(key, count) {
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

  function applyCollapsedSectionState(key) {
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

  function toggleCollapsedSection(key) {
    const config = SECTION_CONFIG[key];
    if (!config || !config.collapsible) {
      return;
    }

    state.collapsedSections[key] = !state.collapsedSections[key];
    applyCollapsedSectionState(key);
    updateSectionTitle(key, sortedByStatus(key).length);
  }

  function wireCollapsibleSection(key) {
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

  function createCard(item, mode) {
    // TODO: Make font size larger for the ingredient name, smaller for the category. Amount same size as name and category in height.
    const card = document.createElement("div");
    card.className = "shop-card";

    const unitPart = item.unit ? ` ${item.unit}` : "";
    const amountPart = item.amount;
    const quantityText = `${amountPart}${unitPart}`.trim();
    const deleteRightHint = `
      <div class="shop-swipe-delete-right-hint" aria-hidden="true">
        <span class="shop-swipe-delete-right-icon">x</span>
        <span class="shop-swipe-delete-right-label">Delete</span>
      </div>`;
    const skipHint = mode === "remaining"
      ? `
      <div class="shop-swipe-skip-hint" aria-hidden="true">
        <span class="shop-swipe-skip-icon">\u22ef</span>
        <span class="shop-swipe-skip-label">Postpone</span>
      </div>`
      : "";
    const deleteHint = mode === "completed"
      ? `
      <div class="shop-swipe-delete-hint" aria-hidden="true">
        <span class="shop-swipe-delete-icon">x</span>
        <span class="shop-swipe-delete-label">Delete</span>
      </div>`
      : "";

    card.innerHTML = `
      ${deleteRightHint}
      ${skipHint}
      ${deleteHint}
      <div class="shop-card-head">
        <div class="shop-card-name-wrap">
          <strong class="shop-item-name">${escapeAttr(item.name)}</strong>
          <span class="shop-item-category muted">${escapeAttr(item.ingredient_type)}</span>
        </div>
        <span class="shop-item-amount muted">${escapeAttr(quantityText)}</span>
      </div>
    `;

    if (mode === "remaining") {
      attachRemainingCardGestures(card, item.id);
    } else if (mode === "completed") {
      attachCompletedCardGestures(card, item.id);
    } else {
      attachRestoreToRemainingClick(card, item.id);
    }
    attachSwipeRightDeleteGesture(card, item.id);

    return card;
  }

  function renderSection(containerId, items, mode, groupByCategory = false) {
    // Render a section (remaining, skipped, completed) with the given items and mode.
    const container = document.getElementById(containerId);
    container.innerHTML = "";
    if (items.length === 0) {
      container.innerHTML = '<div class="empty">No items.</div>';
      return;
    }

    if (!groupByCategory) {
      for (const item of items) {
        container.appendChild(createCard(item, mode));
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

      const title = document.createElement("div");
      title.className = "category-title";
      title.textContent = categoryName;
      group.appendChild(title);

      grouped[categoryName]
        .sort((a, b) => a.name.localeCompare(b.name))
        .forEach((item) => group.appendChild(createCard(item, mode)));

      container.appendChild(group);
    }
  }

  function render() {
    if (DEBUG_MODE) {
      output.style.display = "block";
    } else {
      output.style.display = "none";
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

  async function refreshAndSyncIfNeeded() {
    if (!browserOnline()) {
      setApiReachable(false);
      updateStatusBadges();
      return;
    }

    await refresh();
    if (state.pendingChanges.length > 0) {
      await syncPending(false);
    }
  }

  function hydrateFromServer(payload) {
    // This data transformation looks pointless instead of sjust workign with the server data directly.
    // The servar payload already organises the data by ingredient type, category and status, but here
    // is flattened into a single id-based map with the status with each item.
    const sections = payload.data.sections;
    const merged = {};

    //console.log("Hydrating from server:", payload);

    for (const status of ["remaining", "skipped", "completed"]) {
      const list = sections[status];
      for (const item of list) {
        merged[item.id] = item;
      }
    }

    //console.log("Merged items:", merged);

    state.itemsById = merged;
    state.serverCursor = payload.cursor;
    applyPendingChanges();
    persistCache();
  }

  function queueStatusChange(entryId, status) {
    const id = shoppingItemId(entryId);
    if (id === null || !SHOPPING_STATUSES.has(status)) {
      return;
    }

    state.pendingChanges = state.pendingChanges.filter((change) => shoppingItemId(change.entry_id) !== id);

    state.pendingChanges.push({
      operation: "update",
      entry_id: id,
      payload: { status },
      queued_at: new Date().toISOString(),
    });

    const row = state.itemsById[String(id)];
    if (row) {
      row.status = status;
    }

    persistCache();
  }

  function queueDeleteChange(entryId) {
    const id = shoppingItemId(entryId);
    if (id === null) {
      return;
    }

    state.pendingChanges = state.pendingChanges.filter((change) => shoppingItemId(change.entry_id) !== id);

    state.pendingChanges.push({
      operation: "delete",
      entry_id: id,
      queued_at: new Date().toISOString(),
    });

    delete state.itemsById[String(id)];
    persistCache();
  }

  async function refresh() {
    const payload = await api("/shopping-list/view");
    hydrateFromServer(payload);
    render();
    show(payload);
    return payload;
  }

  async function syncPending(showPayload = true) {
    updateStatusBadges();
    if (state.pendingChanges.length === 0) {
      return { source: "local-cache", applied: [], rejected: [] };
    }

    if (!isOnline()) {
      return {
        source: "local-cache",
        message: "Offline. Pending changes are kept locally.",
        pending_count: state.pendingChanges.length,
      };
    }

    const outgoing = [...state.pendingChanges];
    const payload = await api("/shopping-list/sync", {
      method: "POST",
      body: JSON.stringify({ changes: outgoing }),
    });

    const rejectedIndexes = new Set(
      (Array.isArray(payload.rejected) ? payload.rejected : [])
        .map((row) => row.index)
        .filter((value) => Number.isInteger(value) && value >= 0)
    );

    state.pendingChanges = outgoing.filter((_, idx) => rejectedIndexes.has(idx));
    if (Number.isInteger(payload.server_cursor)) {
      state.serverCursor = payload.server_cursor;
    }

    persistCache();

    try {
      await refresh();
    } catch {
      render();
    }

    if (showPayload) {
      show(payload);
    }

    return payload;
  }

  async function setStatus(entryId, status) {
    if (!SHOPPING_STATUSES.has(status)) {
      throw new Error("Invalid status for shopping mode.");
    }

    queueStatusChange(entryId, status);
    render();

    if (!isOnline()) {
      show({
        source: "local-cache",
        message: "Offline mode: change saved locally and queued for sync.",
        entry_id: entryId,
        status,
      });
      return;
    }

    await syncPending(false);
    show({
      source: "shopping-mode",
      message: "Change synced to server.",
      entry_id: entryId,
      status,
      pending_count: state.pendingChanges.length,
    });
  }

  async function deleteEntry(entryId) {
    queueDeleteChange(entryId);
    render();

    if (!isOnline()) {
      show({
        source: "local-cache",
        message: "Offline mode: delete saved locally and queued for sync.",
        entry_id: entryId,
        pending_count: state.pendingChanges.length,
      });
      return;
    }

    await syncPending(false);
    show({
      source: "shopping-mode",
      message: "Delete synced to server.",
      entry_id: entryId,
      pending_count: state.pendingChanges.length,
    });
  }

  // Event listeners for buttons
  // -----------------------------
  // Toggle instruction visibility
  const instr = document.getElementById("shopping-mode-instructions");
  document.getElementById("toggle-instructions").addEventListener("click", () => {
    if (instr.style.display === "none") {
      instr.style.display = "block";
    } else {
      instr.style.display = "none";
    }
  });

  window.addEventListener("online", () => {
    setApiReachable(true);
    updateStatusBadges();
    run(() => refreshAndSyncIfNeeded());
  });

  window.addEventListener("offline", () => {
    setApiReachable(false);
    updateStatusBadges();
    show({
      source: "local-cache",
      message: "Offline mode enabled. Shopping updates will be queued.",
      pending_count: state.pendingChanges.length,
    });
  });

  // Initial load
  wireCollapsibleSection("skipped");
  wireCollapsibleSection("completed");
  loadCache();
  render();

  run(() => refreshAndSyncIfNeeded());
})();
