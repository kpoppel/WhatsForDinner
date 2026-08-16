(() => {
  const apiPrefix = window.WFD_API_PREFIX;
  const output = document.getElementById("output");
  const CACHE_KEY = "wfd.shopping-mode.v1";
  const SHOPPING_STATUSES = new Set(["remaining", "skipped", "completed"]);

  const state = {
    itemsById: {},
    pendingChanges: [],
    serverCursor: 0,
  };

  function show(data) {
    output.textContent = JSON.stringify(data, null, 2);
  }

  function isOnline() {
    return navigator.onLine !== false;
  }

  function escapeAttr(value) {
    return String(value ?? "")
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
    const response = await fetch(`${apiPrefix}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });

    const data = await response.json();
    if (!response.ok) {
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

  function normalizeShoppingItem(item, fallbackStatus) {
    const id = shoppingItemId(item?.id);
    if (id === null) {
      return null;
    }

    const status = SHOPPING_STATUSES.has(item?.status) ? item.status : fallbackStatus;
    return {
      id,
      name: String(item?.name || "Unnamed"),
      amount: item?.amount,
      unit: item?.unit ? String(item.unit) : "",
      status: SHOPPING_STATUSES.has(status) ? status : "remaining",
      ingredient_type: String(item?.ingredient_type || "Other"),
      store_group: String(item?.store_group || "General"),
    };
  }

  function persistCache() {
    try {
      localStorage.setItem(CACHE_KEY, JSON.stringify(state));
    } catch {
      // Ignore write failures.
    }
  }

  function applyPendingStatuses() {
    for (const change of state.pendingChanges) {
      if (!change || change.operation !== "update") {
        continue;
      }
      const id = shoppingItemId(change.entry_id);
      const status = change.payload?.status;
      if (id === null || !SHOPPING_STATUSES.has(status)) {
        continue;
      }
      const row = state.itemsById[String(id)];
      if (row) {
        row.status = status;
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

    applyPendingStatuses();
    persistCache();
  }

  function updateStatusBadges() {
    const network = document.getElementById("shop-mode-network");
    const pending = document.getElementById("shop-mode-pending");
    network.textContent = isOnline() ? "Status: online" : "Status: offline";
    pending.textContent = `Pending sync: ${state.pendingChanges.length}`;
  }

  function sortedByStatus(status) {
    return Object.values(state.itemsById)
      .filter((item) => item && item.status === status)
      .sort((a, b) => String(a.name).localeCompare(String(b.name)));
  }

  function attachRestoreToRemainingClick(card, entryId) {
    card.addEventListener("click", () => {
      run(() => setStatus(entryId, "remaining"));
    });
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
        run(() => setStatus(entryId, "skipped"));
      }

      isDragging = false;
      deltaX = 0;
    });

    card.addEventListener("click", () => {
      if (suppressClick) {
        suppressClick = false;
        return;
      }
      run(() => setStatus(entryId, "completed"));
    });
  }

  function createCard(item, mode) {
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

  function renderSection(containerId, items, mode) {
    const container = document.getElementById(containerId);
    container.innerHTML = "";
    if (!Array.isArray(items) || items.length === 0) {
      container.innerHTML = '<div class="empty">No items.</div>';
      return;
    }

    for (const item of items) {
      container.appendChild(createCard(item, mode));
    }
  }

  function renderRemainingByCategory(items) {
    const container = document.getElementById("shop-mode-remaining");
    container.innerHTML = "";

    if (!Array.isArray(items) || items.length === 0) {
      container.innerHTML = '<div class="empty">No items.</div>';
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
      group.className = "category";

      const title = document.createElement("div");
      title.className = "category-title";
      title.textContent = category;
      group.appendChild(title);

      grouped[category]
        .sort((a, b) => String(a.name).localeCompare(String(b.name)))
        .forEach((item) => group.appendChild(createCard(item, "remaining")));

      container.appendChild(group);
    }
  }

  function render() {
    renderRemainingByCategory(sortedByStatus("remaining"));
    renderSection("shop-mode-skipped", sortedByStatus("skipped"), "skipped");
    renderSection("shop-mode-completed", sortedByStatus("completed"), "completed");
    updateStatusBadges();
  }

  function hydrateFromServer(payload) {
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

    state.itemsById = merged;
    if (Number.isInteger(payload?.cursor)) {
      state.serverCursor = payload.cursor;
    }
    applyPendingStatuses();
    persistCache();
  }

  function queueStatusChange(entryId, status) {
    const id = shoppingItemId(entryId);
    if (id === null || !SHOPPING_STATUSES.has(status)) {
      return;
    }

    state.pendingChanges = state.pendingChanges.filter((change) => {
      return !(change?.operation === "update" && shoppingItemId(change.entry_id) === id);
    });

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
        .map((row) => Number(row?.index))
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

  document.getElementById("shop-mode-refresh").addEventListener("click", () => run(refresh));
  document.getElementById("shop-mode-sync").addEventListener("click", () => run(() => syncPending(true)));

  window.addEventListener("online", () => {
    updateStatusBadges();
    run(() => syncPending(false));
  });

  window.addEventListener("offline", () => {
    updateStatusBadges();
    show({
      source: "local-cache",
      message: "Offline mode enabled. Shopping updates will be queued.",
      pending_count: state.pendingChanges.length,
    });
  });

  loadCache();
  render();

  run(async () => {
    await refresh();
    if (state.pendingChanges.length > 0) {
      await syncPending(false);
    }
  });
})();
