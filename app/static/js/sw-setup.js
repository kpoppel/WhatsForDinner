export function setupServiceWorker() {
  if (!("serviceWorker" in navigator)) {
    return;
  }

  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/shopping-sw.js", { scope: "/" }).catch(() => {
      // Ignore service worker registration failures.
    });
  });

  // Reload once when a new service worker takes control (new build deployed).
  let _swRefreshing = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!_swRefreshing) {
      _swRefreshing = true;
      window.location.reload();
    }
  });
}
