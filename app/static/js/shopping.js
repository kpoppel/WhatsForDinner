import { loadCache } from "./state.js";
import { render, wireCollapsibleSection, updateStatusBadges, initRender } from "./render.js";
import { isOnline, setApiReachable } from "./api.js";
import { run, refresh, setStatus, deleteEntry, setStatusMany, deleteEntries, refreshAndSyncIfNeeded } from "./sync.js";
import { initGestures, createCard } from "./gestures.js";
import { setupPullToRefresh } from "./ptr.js";
import { setupServiceWorker } from "./sw-setup.js";

// Wire callbacks to break the render ↔ gestures ↔ sync circular dependency.
initGestures({ run, setStatus, deleteEntry, setStatusMany, deleteEntries });
initRender(createCard);

// Toggle instruction visibility.
const instr = document.getElementById("shopping-mode-instructions");
document.getElementById("toggle-instructions").addEventListener("click", () => {
  instr.style.display = instr.style.display === "none" ? "block" : "none";
});

window.addEventListener("online", () => {
  setApiReachable(true);
  updateStatusBadges();
  // Delay sync: the 'online' event fires before routing is stable (e.g. after flight mode).
  setTimeout(() => run(() => refreshAndSyncIfNeeded()), 2000);
});

window.addEventListener("offline", () => {
  setApiReachable(false);
  updateStatusBadges();
});

// navigator.onLine and the 'online' event are unreliable on LANs; probe the API directly.
const apiPrefix = window.WFD_API_PREFIX;
setInterval(async () => {
  if (isOnline()) {
    return;
  }
  try {
    const response = await fetch(`${apiPrefix}/health`, { cache: "no-store" });
    if (response.ok) {
      setApiReachable(true);
      run(() => refreshAndSyncIfNeeded());
    }
  } catch {
    // Still unreachable.
  }
}, 5000);

if (["/app", "/app/"].includes(window.location.pathname)) {
  setupServiceWorker();
}
setupPullToRefresh({ isOnline, run, refreshAndSyncIfNeeded });
wireCollapsibleSection("skipped");
wireCollapsibleSection("completed");
loadCache();
render();
run(() => refreshAndSyncIfNeeded());
