import { render, wireCollapsibleSection, initRender } from "./render.js";
import { isOnline } from "./api.js";
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

window.addEventListener("wfd:connection-restored", () => {
  void run(() => refreshAndSyncIfNeeded());
});

if (["/app", "/app/"].includes(window.location.pathname)) {
  setupServiceWorker();
}
setupPullToRefresh({ isOnline, run, refreshAndSyncIfNeeded });
wireCollapsibleSection("skipped");
wireCollapsibleSection("completed");
render();
run(() => refreshAndSyncIfNeeded());
