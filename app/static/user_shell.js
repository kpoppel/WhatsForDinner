import { probeApiReachability, setApiReachable } from "./js/commands/connectivity.js";
import { apiReachable, browserOnline, isOnline, syncing } from "./js/selectors/connectivity.js";

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
  const networkStatus = document.getElementById("shop-mode-network");
  const networkDot = networkStatus ? networkStatus.querySelector(".status-dot") : null;
  const networkLabel = document.getElementById("shop-mode-network-label");

  if (!shell || !bottomNav || !titleNode || !settingsButton || !exitButton || navButtons.length === 0 || tabPanels.length === 0) {
    return;
  }

  let activeTab = "home";
  const REACHABILITY_INITIAL_DELAY_MS = 6000;
  const REACHABILITY_HEALTHY_DELAY_MS = 300000;
  const REACHABILITY_MAX_DELAY_MS = 300000;
  let reachabilityDelayMs = REACHABILITY_INITIAL_DELAY_MS;
  let reachabilityTimer = null;
  let reachabilityGeneration = 0;
  function applyNetworkStatus() {
    if (!networkStatus || !networkDot || !networkLabel) {
      return;
    }
    const online = isOnline();
    networkDot.classList.toggle("is-online", online && !syncing());
    networkDot.classList.toggle("is-offline", !online && !syncing());
    networkDot.classList.toggle("is-syncing", syncing());
    const label = syncing() ? "Syncing..." : online ? "Online" : "Offline";
    networkLabel.textContent = label;
    networkStatus.setAttribute("aria-label", label);
    networkStatus.setAttribute("title", label);
  }

  function applyOnlineAwareControls() {
    const online = isOnline();
    shell.classList.toggle("wf-is-offline", !online);
    applyNetworkStatus();

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
      return false;
    }

    const reachable = await probeApiReachability();

    applyOnlineAwareControls();
    if (!wasOnline && isOnline()) {
      window.dispatchEvent(new CustomEvent("wfd:connection-restored"));
    }
    return reachable;
  }

  function scheduleReachabilityCheck(delayMs) {
    if (reachabilityTimer !== null) {
      window.clearTimeout(reachabilityTimer);
    }
    reachabilityGeneration += 1;
    const generation = reachabilityGeneration;
    reachabilityTimer = window.setTimeout(async () => {
      if (generation !== reachabilityGeneration) {
        return;
      }
      const reachable = await refreshApiReachability();
      if (generation !== reachabilityGeneration) {
        return;
      }
      reachabilityDelayMs = reachable
        ? REACHABILITY_HEALTHY_DELAY_MS
        : Math.min(reachabilityDelayMs * 2, REACHABILITY_MAX_DELAY_MS);
      scheduleReachabilityCheck(reachabilityDelayMs);
    }, delayMs);
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
    if (activeTab === "shopping-mode") {
      setActiveTab("shop-editor");
      return;
    }
    setActiveTab("home");
  });

  settingsButton.addEventListener("click", () => {
    setActiveTab("settings");
  });

  window.WFD_setActiveTab = setActiveTab;

  window.addEventListener("online", () => {
    reachabilityDelayMs = REACHABILITY_INITIAL_DELAY_MS;
    scheduleReachabilityCheck(0);
  });

  window.addEventListener("offline", () => {
    if (reachabilityTimer !== null) {
      window.clearTimeout(reachabilityTimer);
      reachabilityTimer = null;
    }
    setApiReachable(false);
    applyOnlineAwareControls();
  });

  window.addEventListener("wfd:api-reachability-changed", () => {
    applyOnlineAwareControls();
  });

  window.addEventListener("wfd:sync-state", (event) => {
    if (!(event instanceof CustomEvent)) {
      return;
    }
    applyNetworkStatus();
  });

  window.addEventListener("wfd:manual-connection-check", () => {
    reachabilityDelayMs = REACHABILITY_INITIAL_DELAY_MS;
    scheduleReachabilityCheck(0);
  });

  setActiveTab(activeTab);
  applyOnlineAwareControls();
  scheduleReachabilityCheck(0);
})();
