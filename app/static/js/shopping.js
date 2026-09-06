import { render, wireCollapsibleSection, initRender, updateStatusBadges } from "./render.js";
import { isOnline } from "./selectors/connectivity.js";
import {
  deleteShoppingEntries as deleteEntries,
  deleteShoppingEntry as deleteEntry,
  refreshShoppingAndSync as refreshAndSyncIfNeeded,
  runShoppingAction as run,
  setShoppingStatus as setStatus,
  setShoppingStatusMany as setStatusMany,
} from "./commands/shopping.js";
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

window.addEventListener("wfd:connection-restored", () => {
  void run(() => refreshAndSyncIfNeeded());
});

window.addEventListener("wfd:online-state", () => {
  updateStatusBadges();
});

if (["/app", "/app/"].includes(window.location.pathname)) {
  setupServiceWorker();
}
setupPullToRefresh({ isOnline, run, refreshAndSyncIfNeeded });
wireCollapsibleSection("skipped");
wireCollapsibleSection("completed");
render();
run(() => refreshAndSyncIfNeeded());
