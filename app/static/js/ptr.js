/** Pull-to-refresh gesture adapter that delegates recovery to synchronization. */
let _ptrStartY = 0;
let _ptrDragging = false;
let _ptrIndicator = null;
let _ptrScrollContainers = [];
const PTR_THRESHOLD = 80;

function isScrollable(node) {
  if (!(node instanceof HTMLElement)) {
    return false;
  }
  const style = window.getComputedStyle(node);
  const overflowY = style.overflowY;
  const allowsScroll = overflowY === "auto" || overflowY === "scroll" || overflowY === "overlay";
  return allowsScroll && node.scrollHeight - node.clientHeight > 1;
}

function getScrollableAncestors(target) {
  const containers = [];
  let node = target instanceof Element ? target : null;

  while (node) {
    if (isScrollable(node) && node instanceof HTMLElement) {
      containers.push(node);
    }
    node = node.parentElement;
  }

  const wfContent = document.getElementById("wf-content");
  if (isScrollable(wfContent) && wfContent instanceof HTMLElement && !containers.includes(wfContent)) {
    containers.push(wfContent);
  }

  return containers;
}

function areContainersAtTop(containers) {
  if (!Array.isArray(containers) || containers.length === 0) {
    return window.scrollY === 0;
  }
  return containers.every((container) => container.scrollTop <= 0);
}

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
    _ptrScrollContainers = getScrollableAncestors(e.target);
  }, { passive: true });

  document.addEventListener("touchmove", (e) => {
    const dy = e.touches[0].pageY - _ptrStartY;
    if (dy <= 0) {
      return;
    }

    if (!areContainersAtTop(_ptrScrollContainers)) {
      return;
    }

    if (!isOnline()) {
      return;
    }

    if (e.cancelable) {
      e.preventDefault();
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
    _ptrScrollContainers = [];
  }, { passive: true });

  document.addEventListener("touchcancel", () => {
    if (_ptrIndicator) {
      _ptrIndicator.classList.remove("ptr-ready");
      _ptrIndicator.style.display = "none";
    }
    _ptrDragging = false;
    _ptrScrollContainers = [];
  }, { passive: true });
}
