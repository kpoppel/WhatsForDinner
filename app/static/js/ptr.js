let _ptrStartY = 0;
let _ptrDragging = false;
let _ptrIndicator = null;
const PTR_THRESHOLD = 80;

function getPtrIndicator() {
  if (!_ptrIndicator) {
    _ptrIndicator = document.createElement("div");
    _ptrIndicator.id = "ptr-indicator";
    _ptrIndicator.setAttribute("aria-hidden", "true");
    document.body.prepend(_ptrIndicator);
  }
  return _ptrIndicator;
}

export function setupPullToRefresh({ isOnline, run, refreshAndSyncIfNeeded }) {
  document.addEventListener("touchstart", (e) => {
    _ptrStartY = e.touches[0].pageY;
    _ptrDragging = false;
  }, { passive: true });

  document.addEventListener("touchmove", (e) => {
    const dy = e.touches[0].pageY - _ptrStartY;
    if (dy <= 0 || window.scrollY !== 0) {
      return;
    }
    if (e.cancelable) {
      e.preventDefault();
    }
    if (!isOnline()) {
      return;
    }
    _ptrDragging = true;
    const indicator = getPtrIndicator();
    indicator.style.display = "flex";
    indicator.classList.toggle("ptr-ready", dy >= PTR_THRESHOLD);
  }, { passive: false });

  document.addEventListener("touchend", () => {
    if (!_ptrDragging || !_ptrIndicator) {
      return;
    }
    const wasReady = _ptrIndicator.classList.contains("ptr-ready");
    _ptrIndicator.classList.remove("ptr-ready");
    _ptrIndicator.style.display = "none";
    _ptrDragging = false;
    if (wasReady) {
      run(() => refreshAndSyncIfNeeded());
    }
  }, { passive: true });
}
