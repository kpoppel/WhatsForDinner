import { api } from "./js/store/commands.js";
import { assertRequiredFields } from "./js/contracts.js";

(() => {
  const panel = document.getElementById("wf-tab-settings");
  const dinersValueNode = document.getElementById("wf-settings-default-diners");
  const dinersDownButton = document.getElementById("wf-settings-diners-down");
  const dinersUpButton = document.getElementById("wf-settings-diners-up");
  const reminderTimeInput = document.getElementById("wf-settings-reminder-time");
  const noRepeatValueNode = document.getElementById("wf-settings-no-repeat-days");
  const repeatDownButton = document.getElementById("wf-settings-repeat-down");
  const repeatUpButton = document.getElementById("wf-settings-repeat-up");
  const keywordsContainer = document.getElementById("wf-settings-keywords");
  const selectedNode = document.getElementById("wf-settings-selected");
  const statusNode = document.getElementById("wf-settings-status");
  const refreshButton = document.getElementById("wf-settings-refresh");
  const saveButton = document.getElementById("wf-settings-save");
  const TIME_24H_RE = /^([01]\d|2[0-3]):[0-5]\d$/;
  const keywordCatalog = [];
  const selectedKeywordSet = new Set();

  if (!(panel instanceof HTMLElement)) {
    return;
  }
  if (!(dinersValueNode instanceof HTMLElement)) {
    return;
  }
  if (!(dinersDownButton instanceof HTMLButtonElement)) {
    return;
  }
  if (!(dinersUpButton instanceof HTMLButtonElement)) {
    return;
  }
  if (!(reminderTimeInput instanceof HTMLInputElement)) {
    return;
  }
  if (!(noRepeatValueNode instanceof HTMLElement)) {
    return;
  }
  if (!(repeatDownButton instanceof HTMLButtonElement)) {
    return;
  }
  if (!(repeatUpButton instanceof HTMLButtonElement)) {
    return;
  }
  if (!(keywordsContainer instanceof HTMLElement)) {
    return;
  }
  if (!(selectedNode instanceof HTMLElement)) {
    return;
  }
  if (!(statusNode instanceof HTMLElement)) {
    return;
  }
  if (!(saveButton instanceof HTMLButtonElement)) {
    return;
  }

  const DINERS_MIN = 1;
  const DINERS_MAX = 20;
  const NO_REPEAT_MIN = 0;
  const NO_REPEAT_MAX = 365;

  let defaultDinersValue = 2;
  let noRepeatDaysValue = 14;

  function setStatus(message) {
    statusNode.textContent = message;
  }

  function setAppTab(tabName) {
    if (typeof window.WFD_setActiveTab === "function") {
      window.WFD_setActiveTab(tabName);
    }
  }

  function clampInteger(value, minValue, maxValue) {
    const parsed = Number(value);
    if (!Number.isInteger(parsed)) {
      return minValue;
    }
    if (parsed < minValue) {
      return minValue;
    }
    if (parsed > maxValue) {
      return maxValue;
    }
    return parsed;
  }

  function renderStepperValues() {
    dinersValueNode.textContent = String(defaultDinersValue);
    const dayText = noRepeatDaysValue === 1 ? "day" : "days";
    noRepeatValueNode.textContent = `${noRepeatDaysValue} ${dayText}`;
  }

  function normalize24hTime(rawValue) {
    const value = String(rawValue || "").trim();
    if (TIME_24H_RE.test(value)) {
      return value;
    }

    const match = value.match(/^(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*([AaPp][Mm])$/);
    if (!match) {
      return null;
    }

    const hour12 = Number(match[1]);
    const minute = match[2] || "00";
    const period = match[3].toUpperCase();

    let hour24 = hour12;
    if (period === "AM") {
      if (hour24 === 12) {
        hour24 = 0;
      }
    } else if (period === "PM") {
      if (hour24 !== 12) {
        hour24 += 12;
      }
    }

    return `${String(hour24).padStart(2, "0")}:${minute}`;
  }

  function selectedKeywordIds() {
    const values = Array.from(selectedKeywordSet);
    values.sort((left, right) => left - right);
    return values;
  }

  function renderSelectedKeywords() {
    const labels = [];
    for (const row of keywordCatalog) {
      if (selectedKeywordSet.has(row.id)) {
        labels.push(row.label);
      }
    }

    if (labels.length === 0) {
      selectedNode.textContent = "No keywords selected.";
      return;
    }

    selectedNode.textContent = `Selected: ${labels.join(", ")}`;
  }

  function setSavingState(isSaving) {
    saveButton.disabled = isSaving;
    if (refreshButton instanceof HTMLButtonElement) {
      refreshButton.disabled = isSaving;
    }
    dinersDownButton.disabled = isSaving;
    dinersUpButton.disabled = isSaving;
    reminderTimeInput.disabled = isSaving;
    repeatDownButton.disabled = isSaving;
    repeatUpButton.disabled = isSaving;

    for (const optionButton of keywordsContainer.querySelectorAll("button")) {
      if (optionButton instanceof HTMLButtonElement) {
        optionButton.disabled = isSaving;
      }
    }

    if (isSaving) {
      saveButton.textContent = "Saving...";
      return;
    }

    saveButton.textContent = "Save & Close";
  }

  function keywordOptionNode(keywordId, label) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "wf-keyword-option";
    button.dataset.keywordId = String(keywordId);

    const selected = selectedKeywordSet.has(keywordId);
    if (selected) {
      button.classList.add("is-selected");
    }
    button.setAttribute("aria-pressed", selected ? "true" : "false");

    button.innerHTML = `
      <span class="wf-keyword-check" aria-hidden="true">✓</span>
      <span>${label}</span>
    `;

    button.addEventListener("click", () => {
      if (selectedKeywordSet.has(keywordId)) {
        selectedKeywordSet.delete(keywordId);
      } else {
        selectedKeywordSet.add(keywordId);
      }
      renderKeywordChecklist();
      renderSelectedKeywords();
    });

    return button;
  }

  function renderKeywordChecklist() {
    keywordsContainer.innerHTML = "";

    if (keywordCatalog.length === 0) {
      const emptyNode = document.createElement("p");
      emptyNode.className = "wf-plan-status";
      emptyNode.textContent = "No keywords available.";
      keywordsContainer.appendChild(emptyNode);
      return;
    }

    for (const row of keywordCatalog) {
      keywordsContainer.appendChild(keywordOptionNode(row.id, row.label));
    }
  }

  function assignKeywordOptions(payload) {
    keywordCatalog.length = 0;

    const data = payload.data;
    let rows = [];

    if (Array.isArray(data)) {
      rows = data;
    } else if (data && typeof data === "object" && Array.isArray(data.results)) {
      rows = data.results;
    }

    for (const row of rows) {
      if (!row || typeof row !== "object") {
        continue;
      }
      const id = Number(row.id);
      if (!Number.isInteger(id)) {
        continue;
      }

      let label = "";
      if (typeof row.label === "string" && row.label.trim().length > 0) {
        label = row.label.trim();
      } else if (typeof row.name === "string" && row.name.trim().length > 0) {
        label = row.name.trim();
      } else {
        label = `keyword-${id}`;
      }

      keywordCatalog.push({ id, label });
    }

    keywordCatalog.sort((left, right) => left.label.localeCompare(right.label));
    renderKeywordChecklist();
  }

  function applySelectedKeywords(payload) {
    const selectedIds = payload.selected_keyword_ids;
    selectedKeywordSet.clear();
    if (Array.isArray(selectedIds)) {
      for (const id of selectedIds) {
        const parsed = Number(id);
        if (Number.isInteger(parsed)) {
          selectedKeywordSet.add(parsed);
        }
      }
    }

    renderKeywordChecklist();
    renderSelectedKeywords();
  }

  async function loadSettings() {
    const userSettingsPayload = await api("/config/user-settings");
    const rulesPayload = await api("/config/meal-plan-rules");
    const keywordsPayload = await api("/config/keywords");
    const selectedPayload = await api("/config/keywords/selected");

    assertRequiredFields(userSettingsPayload, ["data"], "User settings response");
    assertRequiredFields(rulesPayload, ["data"], "Meal plan rules response");
    assertRequiredFields(keywordsPayload, ["data"], "Keyword catalog response");
    assertRequiredFields(selectedPayload, ["selected_keyword_ids"], "Selected keywords response");

    const settingsData = userSettingsPayload.data;
    if (settingsData && typeof settingsData === "object") {
      const defaultDiners = Number(settingsData.default_diners);
      if (Number.isInteger(defaultDiners)) {
        defaultDinersValue = clampInteger(defaultDiners, DINERS_MIN, DINERS_MAX);
      }

      const defaultReminderTime = settingsData.default_notification_time;
      if (typeof defaultReminderTime === "string" && defaultReminderTime.trim().length > 0) {
        const normalized = normalize24hTime(defaultReminderTime);
        if (normalized === null) {
          throw new Error("Stored default reminder time is invalid.");
        }
        reminderTimeInput.value = normalized;
      }
    }

    const rulesData = rulesPayload.data;
    if (rulesData && typeof rulesData === "object") {
      const noRepeat = Number(rulesData.no_repeat_days);
      if (Number.isInteger(noRepeat)) {
        noRepeatDaysValue = clampInteger(noRepeat, NO_REPEAT_MIN, NO_REPEAT_MAX);
      }
    }

    renderStepperValues();

    assignKeywordOptions(keywordsPayload);
    applySelectedKeywords(selectedPayload);
  }

  async function saveSettings() {
    const defaultDiners = clampInteger(defaultDinersValue, DINERS_MIN, DINERS_MAX);
    if (!Number.isInteger(defaultDiners) || defaultDiners < DINERS_MIN || defaultDiners > DINERS_MAX) {
      throw new Error("Default diners must be an integer from 1 to 20.");
    }

    const reminderTime = normalize24hTime(reminderTimeInput.value);
    if (reminderTime === null) {
      throw new Error("Default reminder time must be HH:MM in 24-hour format.");
    }

    reminderTimeInput.value = reminderTime;

    const noRepeatDays = clampInteger(noRepeatDaysValue, NO_REPEAT_MIN, NO_REPEAT_MAX);
    if (!Number.isInteger(noRepeatDays) || noRepeatDays < NO_REPEAT_MIN || noRepeatDays > NO_REPEAT_MAX) {
      throw new Error("No-repeat days must be an integer from 0 to 365.");
    }

    setSavingState(true);
    try {
      await api("/config/user-settings", {
        method: "PUT",
        body: JSON.stringify({
          default_diners: defaultDiners,
          default_notification_time: reminderTime,
        }),
      });

      await api("/config/meal-plan-rules", {
        method: "PUT",
        body: JSON.stringify({ no_repeat_days: noRepeatDays }),
      });

      await api("/config/keywords/selected", {
        method: "PUT",
        body: JSON.stringify({ keyword_ids: selectedKeywordIds() }),
      });

      renderSelectedKeywords();
      setStatus("Settings saved.");
      window.dispatchEvent(new CustomEvent("wfd:data-changed", { detail: { source: "settings" } }));
      setAppTab("home");
    } finally {
      setSavingState(false);
    }
  }

  async function runAction(action) {
    try {
      await action();
    } catch (error) {
      if (error instanceof Error) {
        setStatus(error.message);
      } else {
        setStatus(String(error));
      }
    }
  }

  if (refreshButton instanceof HTMLButtonElement) {
    refreshButton.addEventListener("click", () => {
      void runAction(loadSettings);
    });
  }

  dinersDownButton.addEventListener("click", () => {
    defaultDinersValue = clampInteger(defaultDinersValue - 1, DINERS_MIN, DINERS_MAX);
    renderStepperValues();
  });

  dinersUpButton.addEventListener("click", () => {
    defaultDinersValue = clampInteger(defaultDinersValue + 1, DINERS_MIN, DINERS_MAX);
    renderStepperValues();
  });

  repeatDownButton.addEventListener("click", () => {
    noRepeatDaysValue = clampInteger(noRepeatDaysValue - 1, NO_REPEAT_MIN, NO_REPEAT_MAX);
    renderStepperValues();
  });

  repeatUpButton.addEventListener("click", () => {
    noRepeatDaysValue = clampInteger(noRepeatDaysValue + 1, NO_REPEAT_MIN, NO_REPEAT_MAX);
    renderStepperValues();
  });

  saveButton.addEventListener("click", () => {
    void runAction(saveSettings);
  });

  const settingsOpenButton = document.getElementById("wf-settings-btn");
  if (settingsOpenButton) {
    settingsOpenButton.addEventListener("click", () => {
      void runAction(loadSettings);
    });
  }

  void runAction(loadSettings);
})();
