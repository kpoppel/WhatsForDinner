/**
 * Shopping Mode composition root.
 * It wires store hydration, gestures, rendering, sync recovery, pull-to-refresh,
 * cross-tab updates, and service-worker registration without owning model data.
 */
import { loadShoppingCacheCommand } from "./store/commands.js";
import { installCrossTabSync, subscribe } from "./store/index.js";
import { requestRender, wireCollapsibleSection, updateStatusBadges, initRender } from "./render.js";
import { isOnline, setApiReachable } from "./api.js";
import { run, refresh, retryPendingProjections, setStatus, deleteEntry, setStatusMany, deleteEntries, refreshAndSyncIfNeeded } from "./sync.js";
import { initGestures, createCard } from "./gestures.js";
import { setupPullToRefresh } from "./ptr.js";
import { setupServiceWorker } from "./sw-setup.js";

// Wire callbacks to break the render ↔ gestures ↔ sync circular dependency.
initGestures({ run, setStatus, deleteEntry, setStatusMany, deleteEntries });
initRender(createCard);
installCrossTabSync();
subscribe((notification) => {
  if (notification.domain === "shopping" && notification.source === "cross-tab") {
    requestRender({ source: "cross-tab", status: "server", revision: notification.revision, force: true });
  }
});

// Toggle instruction visibility.
const instr = document.getElementById("shopping-mode-instructions");
document.getElementById("toggle-instructions").addEventListener("click", () => {
  instr.style.display = instr.style.display === "none" ? "block" : "none";
});

document.getElementById("shop-mode-pending").addEventListener("click", () => {
  run(retryPendingProjections);
});

window.addEventListener("online", () => {
  setApiReachable(true);
  updateStatusBadges();
  run(() => refreshAndSyncIfNeeded());
});

window.addEventListener("offline", () => {
  setApiReachable(false);
  updateStatusBadges();
});

if (["/app", "/app/"].includes(window.location.pathname)) {
  setupServiceWorker();
}
setupPullToRefresh({ isOnline, run, refreshAndSyncIfNeeded });
wireCollapsibleSection("skipped");
wireCollapsibleSection("completed");
loadShoppingCacheCommand();
requestRender({ source: "cache", status: "cached", force: true });
run(() => refreshAndSyncIfNeeded());
