(() => {
  const apiPrefix = window.WFD_API_PREFIX;

  const homeTab = document.getElementById("wf-tab-home");
  const todayKicker = document.getElementById("wf-home-today-kicker");
  const todayTitle = document.getElementById("wf-home-today-title");
  const todayMeta = document.getElementById("wf-home-today-meta");
  const todayReminders = document.getElementById("wf-home-today-reminders");
  const upcomingList = document.getElementById("wf-home-upcoming-list");
  const openPlansButton = document.getElementById("wf-home-view-plan");
  const editDayButton = document.getElementById("wf-home-edit-plan");

  if (!(homeTab instanceof HTMLElement)) {
    return;
  }
  if (!(todayKicker instanceof HTMLElement)) {
    return;
  }
  if (!(todayTitle instanceof HTMLElement)) {
    return;
  }
  if (!(todayMeta instanceof HTMLElement)) {
    return;
  }
  if (!(todayReminders instanceof HTMLElement)) {
    return;
  }
  if (!(upcomingList instanceof HTMLElement)) {
    return;
  }
  if (!(openPlansButton instanceof HTMLButtonElement)) {
    return;
  }
  if (!(editDayButton instanceof HTMLButtonElement)) {
    return;
  }

  const dayLabel = new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "short",
    day: "numeric",
  });
  const MEAL_PLAN_CACHE_KEY = "wfd.meal-plans.cache.v1";
  const HOME_ACTIVE_PLAN_CACHE_KEY = "wfd.home.active-plan.v1";

  let lastSelectedPlanId = null;
  let todayEntryId = null;

  function readMealPlanCache() {
    try {
      const raw = localStorage.getItem(MEAL_PLAN_CACHE_KEY);
      if (!raw) {
        return { list: [], byId: {} };
      }
      const parsed = JSON.parse(raw);
      const list = Array.isArray(parsed?.list) ? parsed.list : [];
      const byId = parsed?.byId && typeof parsed.byId === "object" ? parsed.byId : {};
      return { list, byId };
    } catch {
      return { list: [], byId: {} };
    }
  }

  function writeMealPlanCache(nextCache) {
    try {
      localStorage.setItem(MEAL_PLAN_CACHE_KEY, JSON.stringify(nextCache));
    } catch {
      // Ignore localStorage failures.
    }
  }

  function readHomeActivePlanCache() {
    try {
      const raw = localStorage.getItem(HOME_ACTIVE_PLAN_CACHE_KEY);
      if (!raw) {
        return null;
      }
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") {
        return null;
      }
      const plan = parsed.plan;
      if (!plan || typeof plan !== "object") {
        return null;
      }
      return {
        plan,
        entries: sortEntries(plan.entries),
      };
    } catch {
      return null;
    }
  }

  function writeHomeActivePlanCache(plan) {
    if (!plan || typeof plan !== "object") {
      return;
    }
    try {
      localStorage.setItem(HOME_ACTIVE_PLAN_CACHE_KEY, JSON.stringify({
        plan,
        updatedAt: new Date().toISOString(),
      }));
    } catch {
      // Ignore localStorage failures.
    }
  }

  function setTab(tabName) {
    if (typeof window.WFD_setActiveTab === "function") {
      window.WFD_setActiveTab(tabName);
    }
  }

  function modeBadgeLabel(mode) {
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

  function modeBadgeClass(mode) {
    if (mode === "leftover") {
      return "wf-badge wf-badge-leftovers";
    }
    if (mode === "takeout") {
      return "wf-badge wf-badge-takeout";
    }
    if (mode === "empty") {
      return "wf-badge";
    }
    return "wf-badge wf-badge-cook";
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function normalizeTimeTo24hInText(input) {
    const source = String(input || "");
    const pattern = /\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*([AaPp][Mm])\b/g;

    return source.replace(pattern, (_match, hourRaw, minuteRaw, periodRaw) => {
      const hour12 = Number(hourRaw);
      if (!Number.isInteger(hour12)) {
        return _match;
      }

      const minute = typeof minuteRaw === "string" ? minuteRaw : "00";
      const period = String(periodRaw).toUpperCase();

      let hour24 = hour12;
      if (period === "AM") {
        if (hour24 === 12) {
          hour24 = 0;
        }
      } else if (period === "PM") {
        if (hour24 !== 12) {
          hour24 += 12;
        }
      } else {
        return _match;
      }

      const hh = String(hour24).padStart(2, "0");
      return `${hh}:${minute}`;
    });
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

  function todayIsoDate() {
    const now = new Date();
    const yyyy = String(now.getFullYear());
    const mm = String(now.getMonth() + 1).padStart(2, "0");
    const dd = String(now.getDate()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd}`;
  }

  function entryReminder(entry) {
    if (entry && typeof entry === "object") {
      const enabled = entry.reminder_enabled === true;
      const textRaw = entry.reminder_text;
      const text = typeof textRaw === "string" ? textRaw.trim() : "";
      if (enabled && text.length > 0) {
        return text;
      }
      if (enabled) {
        return "Meal prep reminder";
      }

      const notesRaw = entry.notes;
      if (typeof notesRaw === "string") {
        const notesText = notesRaw.trim();
        if (notesText.startsWith("{")) {
          try {
            const parsed = JSON.parse(notesText);
            if (parsed && typeof parsed === "object") {
              if (parsed.reminder_enabled === true) {
                const parsedText = parsed.reminder_text;
                if (typeof parsedText === "string" && parsedText.trim().length > 0) {
                  return parsedText.trim();
                }
                return "Meal prep reminder";
              }
            }
          } catch {
            return "";
          }
        }
      }
    }
    return "";
  }

  function titleFromEntry(entry) {
    if (!entry || typeof entry !== "object") {
      return "No meal planned";
    }

    const recipe = entry.recipe;
    if (recipe && typeof recipe === "object") {
      if (typeof recipe.title === "string" && recipe.title.trim().length > 0) {
        return recipe.title.trim();
      }
      if (typeof recipe.name === "string" && recipe.name.trim().length > 0) {
        return recipe.name.trim();
      }
    }

    const mode = String(entry.mode);
    if (mode === "takeout") {
      return "Takeout";
    }
    if (mode === "leftover") {
      return "Leftovers";
    }
    if (mode === "empty") {
      return "No meal planned";
    }

    return "Meal planned";
  }

  function sortEntries(entries) {
    if (!Array.isArray(entries)) {
      return [];
    }
    const ordered = [];
    for (const entry of entries) {
      if (entry && typeof entry === "object") {
        ordered.push(entry);
      }
    }
    ordered.sort((left, right) => Number(left.day_index) - Number(right.day_index));
    return ordered;
  }

  function resolveTodayEntry(entries) {
    const today = todayIsoDate();
    for (const entry of entries) {
      if (String(entry.date) === today) {
        return entry;
      }
    }
    return null;
  }

  function renderToday(entry, shoppingReminderTexts) {
    if (!entry) {
      todayEntryId = null;
      todayKicker.textContent = "Today";
      todayTitle.textContent = "No meal planned";
      todayMeta.innerHTML = '<span>Set up a plan to populate this card.</span>';
      todayReminders.innerHTML = "";
      openPlansButton.textContent = "Open Meal Plans";
      editDayButton.textContent = "Edit Day";
      editDayButton.disabled = true;
      return;
    }

    const entryId = Number(entry.entry_id);
    if (!Number.isInteger(entryId)) {
      todayEntryId = null;
      openPlansButton.textContent = "Open Meal Plans";
      editDayButton.textContent = "Edit Day";
      editDayButton.disabled = true;
      return;
    }
    todayEntryId = entryId;

    const parsedDate = parseIsoDate(String(entry.date));
    if (parsedDate === null) {
      todayKicker.textContent = "TODAY";
    } else {
      todayKicker.textContent = `TODAY • ${dayLabel.format(parsedDate).toUpperCase()}`;
    }

    todayTitle.textContent = titleFromEntry(entry);

    const servings = Number(entry.servings);
    const servingsText = Number.isInteger(servings) ? `${servings} Diners` : "- Diners";
    const mode = String(entry.mode || "planned");

    const reminders = [];

    const mealReminder = normalizeTimeTo24hInText(entryReminder(entry));
    if (mealReminder.length > 0) {
      reminders.push(mealReminder);
    }

    for (const reminder of shoppingReminderTexts) {
      reminders.push(reminder);
    }

    const firstReminder = reminders[0] || "";
    const reminderBadge = firstReminder.length > 0
      ? `<span class="wf-badge wf-badge-notify">🔔 ${escapeHtml(firstReminder)}</span>`
      : "";

    todayMeta.innerHTML = `
      <span>👥 ${escapeHtml(servingsText)}</span>
      <span class="${modeBadgeClass(mode)}">${escapeHtml(modeBadgeLabel(mode))}</span>
      ${reminderBadge}
    `;

    todayReminders.innerHTML = "";
    if (reminders.length > 1) {
      for (let index = 1; index < reminders.length; index += 1) {
        const reminderText = reminders[index];
        const line = document.createElement("p");
        line.className = "wf-home-reminder-line";
        line.textContent = `🔔 ${reminderText}`;
        todayReminders.appendChild(line);
      }
    }

    openPlansButton.textContent = "View Recipe";
    editDayButton.textContent = "Edit";
    editDayButton.disabled = navigator.onLine === false;
  }

  function renderUpcoming(entries) {
    upcomingList.innerHTML = "";

    const today = todayIsoDate();
    const upcoming = [];
    for (const entry of entries) {
      const textDate = String(entry.date);
      if (textDate > today) {
        upcoming.push(entry);
      }
    }

    if (upcoming.length === 0) {
      upcomingList.innerHTML = '<p class="wf-home-empty">No upcoming meals scheduled.</p>';
      return;
    }

    const limit = Math.min(4, upcoming.length);
    for (let index = 0; index < limit; index += 1) {
      const entry = upcoming[index];
      const parsedDate = parseIsoDate(String(entry.date));
      const day = parsedDate === null ? "-" : new Intl.DateTimeFormat("en-US", { weekday: "short" }).format(parsedDate);
      const dateNumber = parsedDate === null ? "-" : String(parsedDate.getDate());
      const mode = String(entry.mode || "planned");
      const servings = Number(entry.servings);
      const servingsText = Number.isInteger(servings) ? `${servings} diners` : "- diners";
      const reminder = entryReminder(entry);
      const reminderBadge = reminder.length > 0 ? '<span class="wf-badge wf-badge-notify">🔔 Reminder</span>' : "";

      const card = document.createElement("article");
      card.className = "wf-day-card";
      card.innerHTML = `
        <div class="wf-day-date">
          <span>${escapeHtml(day)}</span>
          <span>${escapeHtml(dateNumber)}</span>
        </div>
        <div class="wf-day-main">
          <h3>${escapeHtml(titleFromEntry(entry))}</h3>
          <p>👥 ${escapeHtml(servingsText)} • <span class="${modeBadgeClass(mode)}">${escapeHtml(modeBadgeLabel(mode))}</span> ${reminderBadge}</p>
        </div>
        <span class="wf-day-arrow">❯</span>
      `;
      card.addEventListener("click", () => {
        setTab("meal-plans");
      });
      upcomingList.appendChild(card);
    }
  }

  function shoppingReminderTexts(viewPayload) {
    const reminders = [];

    if (!viewPayload || typeof viewPayload !== "object") {
      return reminders;
    }

    const data = viewPayload.data;
    if (!data || typeof data !== "object") {
      return reminders;
    }

    const sections = data.sections;
    if (!sections || typeof sections !== "object") {
      return reminders;
    }

    const names = ["remaining", "skipped", "completed"];
    for (const name of names) {
      const rows = sections[name];
      if (!Array.isArray(rows)) {
        continue;
      }
      for (const row of rows) {
        if (!row || typeof row !== "object") {
          continue;
        }
        if (row.reminder_enabled !== true) {
          continue;
        }
        if (row.reminder_due !== true) {
          continue;
        }
        const rawText = row.reminder_text;
        if (typeof rawText === "string" && rawText.trim().length > 0) {
          reminders.push(normalizeTimeTo24hInText(rawText.trim()));
        }
      }
    }

    return reminders;
  }

  async function fetchActivePlan() {
    const listPayload = await api("/meal-plans/stored");
    const rows = listPayload.data;
    if (!Array.isArray(rows) || rows.length === 0) {
      const cache = readMealPlanCache();
      writeMealPlanCache({ list: [], byId: cache.byId, updatedAt: new Date().toISOString() });
      return { plan: null, entries: [] };
    }

    const cacheBeforeDetail = readMealPlanCache();
    writeMealPlanCache({
      list: rows,
      byId: cacheBeforeDetail.byId,
      updatedAt: new Date().toISOString(),
    });

    const planId = Number(rows[0].plan_id);
    if (!Number.isInteger(planId)) {
      return { plan: null, entries: [] };
    }

    lastSelectedPlanId = planId;
    const detailPayload = await api(`/meal-plans/${planId}`);
    const plan = detailPayload.data;
    if (!plan || typeof plan !== "object") {
      return { plan: null, entries: [] };
    }
    writeHomeActivePlanCache(plan);

    const cache = readMealPlanCache();
    writeMealPlanCache({
      list: cache.list,
      byId: {
        ...cache.byId,
        [String(planId)]: plan,
      },
      updatedAt: new Date().toISOString(),
    });

    const entries = sortEntries(plan.entries);
    return { plan, entries };
  }

  function fetchActivePlanFromCache() {
    const cache = readMealPlanCache();
    const rows = Array.isArray(cache.list) ? cache.list : [];
    if (rows.length === 0) {
      return { plan: null, entries: [] };
    }

    const planId = Number(rows[0].plan_id);
    if (!Number.isInteger(planId)) {
      return { plan: null, entries: [] };
    }

    lastSelectedPlanId = planId;
    const plan = cache.byId[String(planId)];
    if (plan && typeof plan === "object") {
      return {
        plan,
        entries: sortEntries(plan.entries),
      };
    }

    const homeFallback = readHomeActivePlanCache();
    if (homeFallback) {
      const cachedPlanId = Number(homeFallback.plan.plan_id);
      if (Number.isInteger(cachedPlanId)) {
        lastSelectedPlanId = cachedPlanId;
      }
      return homeFallback;
    }

    return { plan: null, entries: [] };
  }

  async function refreshHome() {
    try {
      let planResult;
      try {
        planResult = await fetchActivePlan();
      } catch {
        planResult = fetchActivePlanFromCache();
      }
      const entries = planResult.entries;

      let reminderTexts = [];
      try {
        const shoppingPayload = await api("/shopping-list/view?limit=400");
        reminderTexts = shoppingReminderTexts(shoppingPayload);
      } catch {
        reminderTexts = [];
      }

      const todayEntry = resolveTodayEntry(entries);
      renderToday(todayEntry, reminderTexts);
      renderUpcoming(entries);

      if (navigator.onLine === false) {
        todayMeta.innerHTML += '<span> • Offline cache</span>';
      }
    } catch {
      todayKicker.textContent = "Today";
      todayTitle.textContent = "Unable to load meal data";
      todayMeta.innerHTML = '<span>Open Meal Plans to refresh.</span>';
      todayReminders.innerHTML = "";
      openPlansButton.textContent = "Open Meal Plans";
      editDayButton.textContent = "Edit Day";
      upcomingList.innerHTML = '<p class="wf-home-empty">Unable to load upcoming meals right now.</p>';
      editDayButton.disabled = true;
    }
  }

  openPlansButton.addEventListener("click", () => {
    setTab("meal-plans");
  });

  editDayButton.addEventListener("click", () => {
    if (!Number.isInteger(lastSelectedPlanId) || !Number.isInteger(todayEntryId)) {
      setTab("meal-plans");
      return;
    }

    window.dispatchEvent(new CustomEvent("wfd:open-meal-editor", {
      detail: {
        planId: lastSelectedPlanId,
        entryId: todayEntryId,
      },
    }));
  });

  const homeNavButton = document.querySelector('.wf-nav-btn[data-tab="home"]');
  if (homeNavButton) {
    homeNavButton.addEventListener("click", () => {
      void refreshHome();
    });
  }

  window.addEventListener("wfd:data-changed", () => {
    const visible = homeTab.hidden === false;
    if (visible) {
      void refreshHome();
    }
  });

  void refreshHome();
})();
