import {
  writeActiveMealPlanId,
  writeHomeActivePlanCache,
  writeMealPlanCache,
} from "./js/store/commands.js";
import {
  loadMealPlan,
  loadShoppingList,
  loadStoredMealPlans,
  searchHomeRecipes,
} from "./js/commands/home.js";
import { isOnline } from "./js/selectors/connectivity.js";
import {
  readActiveMealPlanId,
  readHomeActivePlanCache,
  readMealPlanCache,
} from "./js/store/selectors.js";
import { assertRequiredFields } from "./js/contracts.js";

(() => {
  const tandoorBaseUrl = typeof window.WFD_TANDOOR_BASE_URL === "string"
    ? window.WFD_TANDOOR_BASE_URL.trim().replace(/\/+$/, "")
    : "";

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
  const VIEW_RECIPE_LABEL = "View Recipe";
  let lastSelectedPlanId = null;
  let todayEntryId = null;
  let todayRecipeUrl = null;
  let todayRecipeLookupTitle = "";

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
      return "Eating out";
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

  function recipeUrlFromEntry(entry) {
    if (!entry || typeof entry !== "object") {
      return null;
    }
    const recipe = entry.recipe;
    if (!recipe || typeof recipe !== "object") {
      return null;
    }

    const rawUrl = recipe.url;
    if (typeof rawUrl === "string" && rawUrl.trim().length > 0) {
      return rawUrl.trim();
    }

    const recipeId = Number(recipe.id);
    if (!Number.isInteger(recipeId) || recipeId <= 0 || !tandoorBaseUrl) {
      return null;
    }
    return `${tandoorBaseUrl}/recipe/${recipeId}`;
  }

  function recipeLookupTitleFromEntry(entry) {
    if (!entry || typeof entry !== "object") {
      return "";
    }
    const recipe = entry.recipe;
    if (!recipe || typeof recipe !== "object") {
      return "";
    }

    const title = typeof recipe.title === "string" ? recipe.title.trim() : "";
    if (title.length > 0) {
      return title;
    }

    const name = typeof recipe.name === "string" ? recipe.name.trim() : "";
    return name;
  }

  async function resolveRecipeUrlByLookupTitle(title) {
    const query = typeof title === "string" ? title.trim() : "";
    if (query.length === 0 || !tandoorBaseUrl) {
      return null;
    }

    const payload = await searchHomeRecipes(query);
    const data = payload && typeof payload === "object" ? payload.data : null;
    const rows = data && Array.isArray(data.results) ? data.results : [];
    if (rows.length === 0) {
      return null;
    }

    const normalizedQuery = query.toLowerCase();
    let selected = null;
    for (const row of rows) {
      if (!row || typeof row !== "object") {
        continue;
      }
      const label = String(row.name || row.title || "").trim().toLowerCase();
      if (label === normalizedQuery) {
        selected = row;
        break;
      }
    }
    if (!selected) {
      selected = rows.find((row) => row && typeof row === "object") || null;
    }
    if (!selected) {
      return null;
    }

    const recipeId = Number(selected.id);
    if (!Number.isInteger(recipeId) || recipeId <= 0) {
      return null;
    }
    return `${tandoorBaseUrl}/recipe/${recipeId}`;
  }

  function setViewRecipeButton(recipeUrl, lookupTitle = "") {
    todayRecipeUrl = typeof recipeUrl === "string" && recipeUrl.trim().length > 0
      ? recipeUrl.trim()
      : null;
    todayRecipeLookupTitle = typeof lookupTitle === "string" ? lookupTitle.trim() : "";
    openPlansButton.textContent = VIEW_RECIPE_LABEL;
    openPlansButton.disabled = !todayRecipeUrl && todayRecipeLookupTitle.length === 0;
  }

  function setEditDayButton(enabled, label) {
    editDayButton.textContent = label;
    editDayButton.disabled = !enabled;
  }

  function renderHomeFallbackCard(title, metaHtml) {
    todayEntryId = null;
    todayKicker.textContent = "Today";
    todayTitle.textContent = title;
    todayMeta.innerHTML = metaHtml;
    todayReminders.innerHTML = "";
    setViewRecipeButton(null, "");
    setEditDayButton(false, "Edit Day");
  }

  function renderToday(entry, shoppingReminderTexts) {
    if (!entry) {
      renderHomeFallbackCard("No meal planned", '<span>Set up a plan to populate this card.</span>');
      return;
    }

    const entryId = Number(entry.entry_id);
    if (!Number.isInteger(entryId)) {
      todayEntryId = null;
      setViewRecipeButton(null);
      setEditDayButton(false, "Edit Day");
      return;
    }
    todayEntryId = entryId;
    setViewRecipeButton(recipeUrlFromEntry(entry), recipeLookupTitleFromEntry(entry));

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

    setEditDayButton(true, "Edit");
    editDayButton.disabled = !isOnline();
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
    const listPayload = await loadStoredMealPlans();
    assertRequiredFields(listPayload, ["data"], "Meal plan list response");
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

    const preferredId = readActiveMealPlanId();
    const preferredRow = Number.isInteger(preferredId)
      ? rows.find((row) => Number(row?.plan_id) === preferredId)
      : null;
    const planId = Number((preferredRow || rows[0]).plan_id);
    if (!Number.isInteger(planId)) {
      return { plan: null, entries: [] };
    }

    lastSelectedPlanId = planId;
    writeActiveMealPlanId(planId);
    const detailPayload = await loadMealPlan(planId);
    assertRequiredFields(detailPayload, ["data"], "Meal plan detail response");
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

    const preferredId = readActiveMealPlanId();
    const preferredRow = Number.isInteger(preferredId)
      ? rows.find((row) => Number(row?.plan_id) === preferredId)
      : null;
    const planId = Number((preferredRow || rows[0]).plan_id);
    if (!Number.isInteger(planId)) {
      return { plan: null, entries: [] };
    }

    lastSelectedPlanId = planId;
    writeActiveMealPlanId(planId);
    const plan = cache.byId[String(planId)];
    if (plan && typeof plan === "object") {
      return {
        plan,
        entries: sortEntries(plan.entries),
      };
    }

    const homeFallback = readHomeActivePlanCache(sortEntries);
    if (homeFallback) {
      const cachedPlanId = Number(homeFallback.plan.plan_id);
      if (Number.isInteger(cachedPlanId)) {
        lastSelectedPlanId = cachedPlanId;
        writeActiveMealPlanId(cachedPlanId);
      }
      return homeFallback;
    }

    return { plan: null, entries: [] };
  }

  async function fetchPlanWithCacheFallback() {
    try {
      return await fetchActivePlan();
    } catch {
      return fetchActivePlanFromCache();
    }
  }

  async function refreshHome() {
    try {
      const planResult = await fetchPlanWithCacheFallback();
      const entries = planResult.entries;

      let reminderTexts = [];
      try {
        const shoppingPayload = await loadShoppingList(400);
        assertRequiredFields(shoppingPayload, ["data"], "Shopping view response");
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
      renderHomeFallbackCard("Unable to load meal data", '<span>Open Meal Plans to refresh.</span>');
      upcomingList.innerHTML = '<p class="wf-home-empty">Unable to load upcoming meals right now.</p>';
    }
  }

  function renderCachedHome() {
    const planResult = fetchActivePlanFromCache();
    renderToday(resolveTodayEntry(planResult.entries), []);
    renderUpcoming(planResult.entries);
  }

  openPlansButton.addEventListener("click", async () => {
    let targetUrl = todayRecipeUrl;
    if (!targetUrl && todayRecipeLookupTitle.length > 0) {
      try {
        targetUrl = await resolveRecipeUrlByLookupTitle(todayRecipeLookupTitle);
        if (targetUrl) {
          setViewRecipeButton(targetUrl, todayRecipeLookupTitle);
        }
      } catch {
        targetUrl = null;
      }
    }

    if (!targetUrl) {
      return;
    }

    const opened = window.open(targetUrl, "_blank", "noopener,noreferrer");
    if (opened) {
      return;
    }
    window.location.assign(targetUrl);
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

  renderCachedHome();
  void refreshHome();
})();
