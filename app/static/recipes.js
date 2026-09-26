import { createIcons, CalendarPlus, CalendarMinus, Plus, Pencil, Trash2, Search, ListFilter, X } from "lucide";
import { api, apiChat } from "./js/api.js";
import { isOnline } from "./js/selectors/connectivity.js";
import { createMealPlanEntry, loadMealPlan, loadStoredMealPlans, updateMealPlanEntry } from "./js/commands/meal-plans.js";

(() => {
  const root = document.getElementById("wf-tab-recipes");
  const query = document.getElementById("wf-recipes-query");
  const status = document.getElementById("wf-recipes-status");
  const reviewStatus = document.getElementById("wf-recipes-review-status");
  const results = document.getElementById("wf-recipes-results");
  const reviewList = document.getElementById("wf-recipes-review-list");
  const options = document.getElementById("wf-recipes-food-options");
  const tokens = document.getElementById("wf-recipes-food-tokens");
  const searchView = document.getElementById("wf-recipes-search-view");
  const reviewView = document.getElementById("wf-recipes-review-view");
  const chatView = document.getElementById("wf-recipes-chat-view");
  const chatMessages = document.getElementById("wf-recipes-chat-messages");
  const chatInput = document.getElementById("wf-recipes-chat-input");
  const chatStatus = document.getElementById("wf-recipes-chat-status");
  const chatSend = document.getElementById("wf-recipes-chat-send");
  const chatClear = document.getElementById("wf-recipes-chat-clear");
  const modal = document.getElementById("wf-recipe-plan-modal");
  const planSelect = document.getElementById("wf-recipe-plan-select");
  const daySelect = document.getElementById("wf-recipe-day-select");
  const dateField = document.getElementById("wf-recipe-date-field");
  const dayDate = document.getElementById("wf-recipe-date");
  const planStatus = document.getElementById("wf-recipe-plan-status");
  let mode = "name";
  let page = 1;
  let total = 0;
  let selectedFoods = [];
  let uses = [];
  let pendingRecipe = null;
  let selectedPlan = null;
  let timer = 0;
  let revision = 0;
  let searchController = null;
  let usesController = null;
  let conversation = [];
  let chatting = false;

  /** Create an accessible icon action using the same touch target everywhere. */
  function iconButton(icon, label, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "wf-recipes-icon";
    button.title = label;
    button.setAttribute("aria-label", label);
    button.disabled = !isOnline();
    const glyph = document.createElement("i");
    glyph.setAttribute("data-lucide", icon);
    button.append(glyph);
    button.addEventListener("click", onClick);
    return button;
  }

  /** Materialize newly inserted Lucide markers. */
  function paintIcons() {
    createIcons({ icons: { CalendarPlus, CalendarMinus, Plus, Pencil, Trash2, Search, ListFilter, X } });
  }

  /** Display a request error in the active view. */
  function report(error, target = status) {
    target.textContent = error.message;
  }

  /** Load the global exclusion list for both entry routes. */
  async function refreshUses() {
    if (usesController) usesController.abort();
    if (!isOnline()) {
      reviewStatus.textContent = "Offline: recipe exclusions are unavailable.";
      return;
    }
    const controller = new AbortController();
    usesController = controller;
    reviewStatus.textContent = "Loading exclusions...";
    try {
      uses = (await api("/recipe-uses", { signal: controller.signal })).results;
      renderReview();
      reviewStatus.textContent = uses.length ? "" : "No recipes excluded.";
    } catch (error) {
      if (!controller.signal.aborted) report(error, reviewStatus);
    }
  }

  /** Render the current exclusions and their editable dates. */
  function renderReview() {
    reviewList.replaceChildren();
    for (const use of uses) {
      const row = document.createElement("article");
      row.className = "wf-recipes-row wf-recipes-review-row";
      const text = document.createElement("div");
      text.className = "wf-recipes-row-text";
      const name = document.createElement("strong");
      name.textContent = use.title;
      const meta = document.createElement("small");
      meta.textContent = `${use.source === "plan" ? "Meal plan" : "Manual"} · used ${use.used_date} · until ${use.exclusion_until}`;
      text.append(name, meta);
      const actions = document.createElement("div");
      actions.className = "wf-recipes-actions";
      const dateInput = document.createElement("input");
      dateInput.type = "date";
      dateInput.className = "wf-recipes-date";
      dateInput.value = use.used_date;
      dateInput.setAttribute("aria-label", `Last used date for ${use.title}`);
      dateInput.disabled = !isOnline();
      actions.append(dateInput);
      actions.append(iconButton("pencil", `Save last used date for ${use.title}`, async () => {
        try {
          await api(`/recipe-uses/${use.recipe_id}`, {
            method: "PUT", body: JSON.stringify({ used_date: dateInput.value }),
          });
          await refreshUses();
          await searchRecipes();
        } catch (error) { report(error, reviewStatus); }
      }));
      actions.append(iconButton("trash-2", `Remove ${use.title} from Don't Repeat`, async () => {
        if (!window.confirm(`Remove ${use.title} from Don't Repeat?`)) return;
        try {
          await api(`/recipe-uses/${use.recipe_id}`, { method: "DELETE" });
          await refreshUses();
          await searchRecipes();
        } catch (error) { report(error, reviewStatus); }
      }));
      row.append(text, actions);
      reviewList.append(row);
    }
    paintIcons();
  }

  /** Show search, AI ideas, or the global review surface. */
  function showView(view) {
    const reviewing = view === "review";
    const chattingView = view === "chat";
    if (reviewing || chattingView) {
      ++revision;
      if (searchController) searchController.abort();
    }
    searchView.hidden = reviewing || chattingView;
    chatView.hidden = !chattingView;
    reviewView.hidden = !reviewing;
    for (const [id, active] of [["wf-recipes-search-tab", view === "search"], ["wf-recipes-chat-tab", chattingView], ["wf-recipes-review-tab", reviewing]]) {
      const button = document.getElementById(id);
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", String(active));
    }
    if (reviewing) void refreshUses();
    else if (!chattingView) {
      const current = ++revision;
      void refreshUses().then(() => {
        if (current === revision && !root.hidden) void searchRecipes();
      });
    } else {
      chatInput.focus();
    }
  }

  /** Render chat text without interpreting model output as HTML. */
  function renderConversation() {
    chatMessages.replaceChildren();
    for (const message of conversation) {
      const bubble = document.createElement("article");
      bubble.className = `wf-recipes-chat-message wf-recipes-chat-${message.role}`;
      const label = document.createElement("strong");
      label.textContent = message.role === "user" ? "You" : "Recipe idea";
      const body = document.createElement("p");
      body.textContent = message.content;
      bubble.append(label, body);
      chatMessages.append(bubble);
    }
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  /** Submit the conversation, committing the new turn only after a successful reply. */
  async function askForRecipe(event) {
    event.preventDefault();
    const text = chatInput.value.trim();
    if (!text || chatting || !isOnline()) return;
    const messages = [...conversation.slice(-18), { role: "user", content: text }];
    chatting = true;
    chatSend.disabled = true;
    chatInput.disabled = true;
    chatClear.disabled = true;
    chatStatus.textContent = "Thinking of a recipe...";
    try {
      const response = await apiChat("/recipes/chat", { method: "POST", body: JSON.stringify({ messages }) });
      conversation = [...messages, { role: "model", content: response.reply }];
      chatInput.value = "";
      chatStatus.textContent = "";
      renderConversation();
    } catch (error) { report(error, chatStatus); }
    finally {
      chatting = false;
      chatInput.disabled = false;
      chatClear.disabled = false;
      chatSend.disabled = !isOnline();
    }
  }

  /** Render compact search rows and their plan/exclusion actions. */
  function renderResults(rows) {
    results.replaceChildren();
    if (!rows.length) status.textContent = "No matching recipes.";
    for (const recipe of rows) {
      const existing = uses.find((use) => use.recipe_id === recipe.id);
      const row = document.createElement("article");
      row.className = "wf-recipes-row";
      const text = document.createElement("div");
      text.className = "wf-recipes-row-text";
      const name = document.createElement("strong");
      name.textContent = recipe.title;
      const meta = document.createElement("small");
      meta.textContent = `${mode === "ingredients" ? `${recipe.match_count} ingredients matched` : "Recipe"}${existing ? ` · excluded until ${existing.exclusion_until}` : ""}`;
      text.append(name, meta);
      const actions = document.createElement("div");
      actions.className = "wf-recipes-actions";
      actions.append(iconButton("calendar-plus", `Add ${recipe.title} to meal plan`, () => { void openPlanPicker(recipe); }));
      if (existing) {
        actions.append(iconButton("calendar-minus", `Remove ${recipe.title} from Don't Repeat`, async () => {
          if (!window.confirm(`Remove ${recipe.title} from Don't Repeat?`)) return;
          try {
            await api(`/recipe-uses/${recipe.id}`, { method: "DELETE" });
            await refreshUses();
            await searchRecipes();
          } catch (error) { report(error); }
        }));
      } else {
        actions.append(iconButton("plus", `Add ${recipe.title} to Don't Repeat`, async () => {
          try {
            await api("/recipe-uses", { method: "POST", body: JSON.stringify({ recipe_id: recipe.id }) });
            await refreshUses();
            await searchRecipes();
          } catch (error) { report(error); }
        }));
      }
      row.append(text, actions);
      results.append(row);
    }
    paintIcons();
    document.getElementById("wf-recipes-page-label").textContent = total ? `${page} / ${Math.ceil(total / 20)}` : "";
    document.getElementById("wf-recipes-prev").disabled = page <= 1;
    document.getElementById("wf-recipes-next").disabled = page * 20 >= total;
  }

  /** Ask the API for a globally ranked ingredient page or a Tandoor search page. */
  async function searchRecipes() {
    const current = ++revision;
    if (searchController) searchController.abort();
    if (root.hidden || reviewView.hidden === false) return;
    if (!isOnline()) {
      results.replaceChildren();
      status.textContent = "Offline: recipe search is unavailable.";
      return;
    }
    if (mode === "ingredients" && !selectedFoods.length) {
      total = 0;
      status.textContent = "Select an ingredient to search.";
      renderResults([]);
      status.textContent = "Select an ingredient to search.";
      return;
    }
    status.textContent = "Searching recipes...";
    const params = new URLSearchParams({ mode, page: String(page), page_size: "20", search: mode === "name" ? query.value.trim() : "", keywords_only: String(document.getElementById("wf-recipes-keywords").checked) });
    for (const food of selectedFoods) params.append("food_ids", String(food.id));
    const controller = new AbortController();
    searchController = controller;
    try {
      const data = await api(`/recipes/find?${params}`, { signal: controller.signal });
      if (current !== revision) return;
      total = data.count;
      status.textContent = `${total} recipes`;
      renderResults(data.results);
    } catch (error) { if (current === revision && !controller.signal.aborted) report(error); }
  }

  /** Show matching Tandoor foods, retaining their exact IDs. */
  async function findFoods() {
    if (mode !== "ingredients" || !query.value.trim() || !isOnline()) {
      options.hidden = true;
      return;
    }
    try {
      const data = await api(`/recipe-foods?search=${encodeURIComponent(query.value.trim())}`);
      options.replaceChildren();
      for (const food of data.results) {
        if (selectedFoods.some((row) => row.id === food.id)) continue;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "wf-recipes-food-option";
        button.textContent = food.name;
        button.addEventListener("click", () => {
          selectedFoods.push(food);
          query.value = "";
          options.hidden = true;
          renderTokens();
          page = 1;
          void searchRecipes();
        });
        options.append(button);
      }
      options.hidden = !options.childElementCount;
    } catch (error) { report(error); }
  }

  /** Draw removable ingredient tokens for selected food IDs. */
  function renderTokens() {
    tokens.replaceChildren();
    for (const food of selectedFoods) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "wf-recipes-token";
      button.textContent = `${food.name} ×`;
      button.setAttribute("aria-label", `Remove ${food.name}`);
      button.addEventListener("click", () => {
        selectedFoods = selectedFoods.filter((row) => row.id !== food.id);
        renderTokens();
        page = 1;
        void searchRecipes();
      });
      tokens.append(button);
    }
  }

  /** Select which API search contract the input uses. */
  function setMode(next) {
    mode = next;
    page = 1;
    query.value = "";
    query.placeholder = next === "name" ? "Search recipes" : "Find a Tandoor food";
    tokens.hidden = next === "name";
    options.hidden = true;
    for (const [id, active] of [["wf-recipes-name", next === "name"], ["wf-recipes-ingredients", next === "ingredients"]]) {
      const button = document.getElementById(id);
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    }
    void searchRecipes();
  }

  /** Populate the saved plan and day picker for a recipe. */
  async function openPlanPicker(recipe) {
    pendingRecipe = recipe;
    modal.hidden = false;
    planStatus.textContent = "Loading saved plans...";
    try {
      const plans = (await loadStoredMealPlans()).data;
      planSelect.replaceChildren();
      for (const plan of plans) {
        const option = document.createElement("option");
        option.value = String(plan.plan_id);
        option.textContent = `${plan.start_date} · ${plan.length_days} days`;
        planSelect.append(option);
      }
      if (!plans.length) {
        planStatus.textContent = "Create a meal plan first.";
        return;
      }
      await loadDays();
    } catch (error) { report(error, planStatus); }
  }

  /** Retrieve the chosen plan and expose existing days plus a dated new day. */
  async function loadDays() {
    try {
      selectedPlan = (await loadMealPlan(Number(planSelect.value))).data;
      daySelect.replaceChildren();
      for (const entry of selectedPlan.entries) {
        const option = document.createElement("option");
        option.value = String(entry.entry_id);
        option.textContent = `${entry.date} · ${entry.recipes.length} recipes`;
        daySelect.append(option);
      }
      const newDay = document.createElement("option");
      newDay.value = "new";
      newDay.textContent = "New dated day";
      daySelect.append(newDay);
      dayDate.value = "";
      dateField.hidden = daySelect.value !== "new";
      planStatus.textContent = "";
    } catch (error) { report(error, planStatus); }
  }

  /** Add the recipe with the selected day's scheduled use date. */
  async function addToPlan(event) {
    event.preventDefault();
    if (!selectedPlan || !pendingRecipe || !isOnline()) return;
    const recipe = { id: pendingRecipe.id, title: pendingRecipe.title, purpose: "meal" };
    try {
      if (daySelect.value === "new") {
        if (!dayDate.value) {
          planStatus.textContent = "Choose the new day's date.";
          return;
        }
        await createMealPlanEntry(selectedPlan.plan_id, { date: dayDate.value, mode: "planned", recipes: [recipe] });
      } else {
        const entry = selectedPlan.entries.find((row) => row.entry_id === Number(daySelect.value));
        await updateMealPlanEntry(selectedPlan.plan_id, entry.entry_id, { mode: "planned", recipes: [...entry.recipes, recipe] });
      }
      modal.hidden = true;
      status.textContent = `${pendingRecipe.title} added to meal plan.`;
      window.dispatchEvent(new CustomEvent("wfd:data-changed", { detail: { source: "recipes" } }));
      await refreshUses();
      await searchRecipes();
    } catch (error) { report(error, planStatus); }
  }

  document.getElementById("wf-recipes-search-tab").addEventListener("click", () => showView("search"));
  document.getElementById("wf-recipes-chat-tab").addEventListener("click", () => showView("chat"));
  document.getElementById("wf-recipes-review-tab").addEventListener("click", () => showView("review"));
  document.getElementById("wf-recipes-chat-form").addEventListener("submit", (event) => { void askForRecipe(event); });
  chatClear.addEventListener("click", () => {
    if (chatting) return;
    conversation = [];
    chatStatus.textContent = "";
    renderConversation();
    chatInput.focus();
  });
  document.getElementById("wf-recipes-review-add").addEventListener("click", () => { showView("search"); query.focus(); });
  document.getElementById("wf-recipes-name").addEventListener("click", () => setMode("name"));
  document.getElementById("wf-recipes-ingredients").addEventListener("click", () => setMode("ingredients"));
  document.getElementById("wf-recipes-form").addEventListener("submit", (event) => { event.preventDefault(); page = 1; void searchRecipes(); });
  query.addEventListener("input", () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      if (mode === "ingredients") void findFoods();
      else { page = 1; void searchRecipes(); }
    }, 300);
  });
  document.getElementById("wf-recipes-keywords").addEventListener("change", () => { page = 1; void searchRecipes(); });
  document.getElementById("wf-recipes-prev").addEventListener("click", () => { page -= 1; void searchRecipes(); });
  document.getElementById("wf-recipes-next").addEventListener("click", () => { page += 1; void searchRecipes(); });
  planSelect.addEventListener("change", () => { void loadDays(); });
  daySelect.addEventListener("change", () => { dateField.hidden = daySelect.value !== "new"; });
  document.getElementById("wf-recipe-plan-cancel").addEventListener("click", () => { modal.hidden = true; });
  document.getElementById("wf-recipe-plan-form").addEventListener("submit", (event) => { void addToPlan(event); });
  window.addEventListener("wfd:open-recipe-review", () => showView("review"));
  window.addEventListener("wfd:open-recipe-search", () => showView("search"));
  window.addEventListener("wfd:tab-changed", (event) => {
    if (event.detail.tab !== "recipes") {
      ++revision;
      window.clearTimeout(timer);
      if (searchController) searchController.abort();
      if (usesController) usesController.abort();
    }
  });
  window.addEventListener("wfd:data-changed", (event) => {
    if (event.detail.source === "meal-plans" && !root.hidden) void refreshUses();
  });
  window.addEventListener("wfd:online-state", () => {
    chatSend.disabled = chatting || !isOnline();
    if (!root.hidden && isOnline()) void refreshUses();
  });
  for (const [id, icon] of [["wf-recipes-name", "search"], ["wf-recipes-ingredients", "list-filter"]]) {
    const glyph = document.createElement("i");
    glyph.setAttribute("data-lucide", icon);
    document.getElementById(id).replaceChildren(glyph);
  }
  paintIcons();
})();