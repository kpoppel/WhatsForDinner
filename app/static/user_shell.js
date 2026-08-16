(() => {
  const TAB_META = {
    home: { title: "Today's Dinner" },
    "meal-plans": { title: "Saved Meal Plans" },
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

  if (!shell || !bottomNav || !titleNode || !settingsButton || !exitButton || navButtons.length === 0 || tabPanels.length === 0) {
    return;
  }

  let activeTab = "home";

  function setActiveTab(nextTab) {
    if (!TAB_META[nextTab]) {
      return;
    }

    activeTab = nextTab;

    for (const button of navButtons) {
      const isActive = button.dataset.tab === nextTab;
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
    shell.classList.toggle("in-shopping-mode", isShoppingMode);
    bottomNav.hidden = isShoppingMode;
    settingsButton.hidden = isShoppingMode;
    exitButton.hidden = !isShoppingMode;

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
    setActiveTab("home");
  });

  settingsButton.addEventListener("click", () => {
    window.alert("Settings panel is planned for Phase 4.");
  });

  setActiveTab(activeTab);
})();
