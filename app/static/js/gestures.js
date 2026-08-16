import { escapeAttr } from "./utils.js";
import { suppressNextCardClick, consumeSuppressedCardClick } from "./render.js";

// Injected by initGestures() from shopping.js to avoid a circular dependency with sync.js.
let _run, _setStatus, _deleteEntry;

export function initGestures({ run, setStatus, deleteEntry }) {
  _run = run;
  _setStatus = setStatus;
  _deleteEntry = deleteEntry;
}

export function attachSwipeRightDeleteGesture(card, entryId) {
  let startX = 0;
  let startY = 0;
  let deltaX = 0;
  let isDragging = false;

  card.addEventListener("touchstart", (event) => {
    const touch = event.changedTouches?.[0];
    if (!touch) {
      return;
    }
    startX = touch.clientX;
    startY = touch.clientY;
    deltaX = 0;
    isDragging = false;
    card.classList.remove("swiping-delete-right");
    card.style.setProperty("--swipe-delete-right-progress", "0");
  });

  card.addEventListener("touchmove", (event) => {
    const touch = event.changedTouches?.[0];
    if (!touch) {
      return;
    }
    deltaX = touch.clientX - startX;
    const deltaY = touch.clientY - startY;
    if (Math.abs(deltaX) <= Math.abs(deltaY) || deltaX <= 0) {
      return;
    }
    isDragging = true;
    const clamped = Math.max(Math.min(deltaX, 140), 0);
    card.style.transform = `translateX(${clamped}px)`;
    card.classList.toggle("swiping-delete-right", clamped > 20);
    const progress = Math.min(Math.abs(clamped) / 140, 1);
    card.style.setProperty("--swipe-delete-right-progress", String(progress));
    if (event.cancelable) {
      event.preventDefault();
    }
  }, { passive: false });

  card.addEventListener("touchend", () => {
    const shouldDelete = isDragging && deltaX > 80;
    card.style.transform = "";
    card.classList.remove("swiping-delete-right");
    card.style.setProperty("--swipe-delete-right-progress", "0");
    if (shouldDelete) {
      suppressNextCardClick(card);
      _run(() => _deleteEntry(entryId));
    }
    isDragging = false;
    deltaX = 0;
  });

  card.addEventListener("click", (event) => {
    if (consumeSuppressedCardClick(card)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);
}

export function attachRestoreToRemainingClick(card, entryId) {
  card.addEventListener("click", () => {
    if (consumeSuppressedCardClick(card)) {
      return;
    }
    _run(() => _setStatus(entryId, "remaining"));
  });
}

export function attachRemainingCardGestures(card, entryId) {
  let startX = 0;
  let startY = 0;
  let deltaX = 0;
  let isDragging = false;

  card.addEventListener("touchstart", (event) => {
    const touch = event.changedTouches?.[0];
    if (!touch) {
      return;
    }
    startX = touch.clientX;
    startY = touch.clientY;
    deltaX = 0;
    isDragging = false;
    card.classList.remove("swiping");
    card.style.setProperty("--swipe-skip-progress", "0");
  });

  card.addEventListener("touchmove", (event) => {
    const touch = event.changedTouches?.[0];
    if (!touch) {
      return;
    }
    deltaX = touch.clientX - startX;
    const deltaY = touch.clientY - startY;
    if (Math.abs(deltaX) <= Math.abs(deltaY)) {
      return;
    }
    isDragging = true;
    const clamped = Math.max(Math.min(deltaX, 0), -140);
    card.style.transform = `translateX(${clamped}px)`;
    card.classList.toggle("swiping", clamped < -20);
    const progress = Math.min(Math.abs(clamped) / 140, 1);
    card.style.setProperty("--swipe-skip-progress", String(progress));
    if (event.cancelable) {
      event.preventDefault();
    }
  }, { passive: false });

  card.addEventListener("touchend", () => {
    const shouldSkip = isDragging && deltaX < -80;
    card.style.transform = "";
    card.classList.remove("swiping");
    card.style.setProperty("--swipe-skip-progress", "0");
    if (shouldSkip) {
      suppressNextCardClick(card);
      _run(() => _setStatus(entryId, "skipped"));
    }
    isDragging = false;
    deltaX = 0;
  });

  card.addEventListener("click", () => {
    if (consumeSuppressedCardClick(card)) {
      return;
    }
    _run(() => _setStatus(entryId, "completed"));
  });
}

export function attachCompletedCardGestures(card, entryId) {
  let startX = 0;
  let startY = 0;
  let deltaX = 0;
  let isDragging = false;

  card.addEventListener("touchstart", (event) => {
    const touch = event.changedTouches?.[0];
    if (!touch) {
      return;
    }
    startX = touch.clientX;
    startY = touch.clientY;
    deltaX = 0;
    isDragging = false;
    card.classList.remove("swiping-delete");
    card.style.setProperty("--swipe-delete-progress", "0");
  });

  card.addEventListener("touchmove", (event) => {
    const touch = event.changedTouches?.[0];
    if (!touch) {
      return;
    }
    deltaX = touch.clientX - startX;
    const deltaY = touch.clientY - startY;
    if (Math.abs(deltaX) <= Math.abs(deltaY)) {
      return;
    }
    isDragging = true;
    const clamped = Math.max(Math.min(deltaX, 0), -140);
    card.style.transform = `translateX(${clamped}px)`;
    card.classList.toggle("swiping-delete", clamped < -20);
    const progress = Math.min(Math.abs(clamped) / 140, 1);
    card.style.setProperty("--swipe-delete-progress", String(progress));
    if (event.cancelable) {
      event.preventDefault();
    }
  }, { passive: false });

  card.addEventListener("touchend", () => {
    const shouldDelete = isDragging && deltaX < -80;
    card.style.transform = "";
    card.classList.remove("swiping-delete");
    card.style.setProperty("--swipe-delete-progress", "0");
    if (shouldDelete) {
      suppressNextCardClick(card);
      _run(() => _deleteEntry(entryId));
    }
    isDragging = false;
    deltaX = 0;
  });

  card.addEventListener("click", () => {
    if (consumeSuppressedCardClick(card)) {
      return;
    }
    _run(() => _setStatus(entryId, "remaining"));
  });
}

export function createCard(item, mode) {
  const card = document.createElement("div");
  card.className = "shop-card";

  const unitPart = item.unit ? ` ${item.unit}` : "";
  const quantityText = `${item.amount}${unitPart}`.trim();

  const deleteRightHint = `
    <div class="shop-swipe-delete-right-hint" aria-hidden="true">
      <span class="shop-swipe-delete-right-icon">x</span>
      <span class="shop-swipe-delete-right-label">Delete</span>
    </div>`;
  const skipHint = mode === "remaining"
    ? `
    <div class="shop-swipe-skip-hint" aria-hidden="true">
      <span class="shop-swipe-skip-icon">\u22ef</span>
      <span class="shop-swipe-skip-label">Postpone</span>
    </div>`
    : "";
  const deleteHint = mode === "completed"
    ? `
    <div class="shop-swipe-delete-hint" aria-hidden="true">
      <span class="shop-swipe-delete-icon">x</span>
      <span class="shop-swipe-delete-label">Delete</span>
    </div>`
    : "";

  card.innerHTML = `
    ${deleteRightHint}
    ${skipHint}
    ${deleteHint}
    <div class="shop-card-head">
      <div class="shop-card-name-wrap">
        <strong class="shop-item-name">${escapeAttr(item.name)}</strong>
        <span class="shop-item-category muted">${escapeAttr(item.ingredient_type)}</span>
      </div>
      <span class="shop-item-amount muted">${escapeAttr(quantityText)}</span>
    </div>
  `;

  if (mode === "remaining") {
    attachRemainingCardGestures(card, item.id);
  } else if (mode === "completed") {
    attachCompletedCardGestures(card, item.id);
  } else {
    attachRestoreToRemainingClick(card, item.id);
  }
  attachSwipeRightDeleteGesture(card, item.id);

  return card;
}
