import { probeApiReachability, setApiReachable } from "./js/commands/connectivity.js";
import { apiReachable, browserOnline, isOnline } from "./js/selectors/connectivity.js";

(() => {
  const TAB_META = {
    home: { title: "Today's Dinner" },
    settings: { title: "Settings" },
    "meal-plans": { title: "Saved Meal Plans" },
    "meal-plan-detail": { title: "Meal Plan Schedule" },
    "shop-editor": { title: "Shopping List Editor" },
    "shopping-mode": { title: "🛒 Shopping Mode" },
  };

  const shell = document.querySelector(".wf-shell");
  const bottomNav = document.querySelector(".wf-bottom-nav");
  const titleNode = document.getElementById("wf-view-title");
  const settingsButton = document.getElementById("wf-settings-btn");
  const exitButton = document.getElementById("wf-exit-btn");
  const shoppingControls = Array.from(document.querySelectorAll(".wf-shop-control"));
  const navButtons = Array.from(document.querySelectorAll(".wf-nav-btn"));
  const tabPanels = Array.from(document.querySelectorAll("[data-tab-panel]"));
  const onlineAwareControls = Array.from(document.querySelectorAll("[data-online-behavior]"));

  if (!shell || !bottomNav || !titleNode || !settingsButton || !exitButton || navButtons.length === 0 || tabPanels.length === 0) {
    return;
  }

  let activeTab = "home";

  function applyOnlineAwareControls() {
    const online = isOnline();
    shell.classList.toggle("wf-is-offline", !online);

    for (const control of onlineAwareControls) {
      const behavior = String(control.getAttribute("data-online-behavior") || "disable").trim().toLowerCase();
      const offlineTitle = String(control.getAttribute("data-offline-title") || "Offline: unavailable.");
      const hasDisableProperty = (
        control instanceof HTMLButtonElement
        || control instanceof HTMLInputElement
        || control instanceof HTMLSelectElement
        || control instanceof HTMLTextAreaElement
      );

      if (behavior === "hide") {
        control.hidden = !online;
      }

      if (behavior === "disable" && hasDisableProperty) {
        if (!control.dataset.onlineTitle) {
          control.dataset.onlineTitle = control.title || "";
        }
        control.disabled = !online;
        control.setAttribute("aria-disabled", String(!online));
        control.title = online ? (control.dataset.onlineTitle || "") : offlineTitle;
      }
    }

    window.dispatchEvent(new CustomEvent("wfd:online-state", {
      detail: {
        online,
        browserOnline: browserOnline(),
        apiReachable: apiReachable(),
      },
    }));
  }

  async function refreshApiReachability() {
    const wasOnline = isOnline();
    if (!browserOnline()) {
      setApiReachable(false);
      applyOnlineAwareControls();
      return;
    }

    await probeApiReachability();

    applyOnlineAwareControls();
    if (!wasOnline && isOnline()) {
      window.dispatchEvent(new CustomEvent("wfd:connection-restored"));
    }
  }

  function setActiveTab(nextTab) {
    if (!TAB_META[nextTab]) {
      return;
    }

    activeTab = nextTab;

    for (const button of navButtons) {
      const isMealPlansBucket = nextTab === "meal-plan-detail" && button.dataset.tab === "meal-plans";
      const isActive = button.dataset.tab === nextTab || isMealPlansBucket;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-current", isActive ? "page" : "false");
    }

    for (const panel of tabPanels) {
      const isActive = panel.dataset.tabPanel === nextTab;
      panel.classList.toggle("is-active", isActive);
      panel.hidden = !isActive;
    }

    titleNode.textContent = TAB_META[nextTab].title;

    const isShoppingMode = nextTab === "shopping-mode";
    const isMealPlanDetail = nextTab === "meal-plan-detail";
    shell.classList.toggle("in-shopping-mode", isShoppingMode);
    bottomNav.hidden = isShoppingMode;
    settingsButton.hidden = isShoppingMode;

    if (isShoppingMode) {
      exitButton.hidden = false;
      exitButton.textContent = "← Exit";
      exitButton.setAttribute("aria-label", "Exit shopping mode");
    } else if (isMealPlanDetail) {
      exitButton.hidden = false;
      exitButton.textContent = "<- Back";
      exitButton.setAttribute("aria-label", "Back to meal plans");
    } else {
      exitButton.hidden = true;
      exitButton.textContent = "← Exit";
      exitButton.setAttribute("aria-label", "Exit");
    }

    for (const control of shoppingControls) {
      control.hidden = !isShoppingMode;
    }
  }

  for (const button of navButtons) {
    button.addEventListener("click", () => {
      setActiveTab(String(button.dataset.tab || ""));
    });
  }

  exitButton.addEventListener("click", () => {
    if (activeTab === "meal-plan-detail") {
      setActiveTab("meal-plans");
      return;
    }
    setActiveTab("home");
  });

  settingsButton.addEventListener("click", () => {
    setActiveTab("settings");
  });

  window.WFD_setActiveTab = setActiveTab;

  window.addEventListener("online", () => {
    void refreshApiReachability();
  });

  window.addEventListener("offline", () => {
    setApiReachable(false);
    applyOnlineAwareControls();
  });

  setActiveTab(activeTab);
  applyOnlineAwareControls();
  void refreshApiReachability();
  setInterval(() => {
    void refreshApiReachability();
  }, 6000);
})();
