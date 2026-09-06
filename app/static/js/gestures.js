import { escapeAttr } from "./utils.js";
import { suppressNextCardClick, consumeSuppressedCardClick } from "./render.js";

// Injected by initGestures() from shopping.js to avoid a circular dependency with sync.js.
let _run, _setStatus, _deleteEntry, _setStatusMany, _deleteEntries;

export function initGestures({ run, setStatus, deleteEntry, setStatusMany, deleteEntries }) {
  _run = run;
  _setStatus = setStatus;
  _deleteEntry = deleteEntry;
  _setStatusMany = setStatusMany;
  _deleteEntries = deleteEntries;
}

function normalizeEntryIds(value) {
  if (Array.isArray(value)) {
    return value
      .map((entryId) => Number(entryId))
      .filter((entryId) => Number.isInteger(entryId) && entryId !== 0);
  }
  const single = Number(value);
  return Number.isInteger(single) && single !== 0 ? [single] : [];
}

const SWIPE_THRESHOLD = 80;
const SWIPE_DISTANCE = 140;

function attachSwipeTracking(card, onSwipe) {
  const actionShell = card.parentElement;
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
    const clamped = Math.max(Math.min(deltaX, SWIPE_DISTANCE), -SWIPE_DISTANCE);
    card.style.transform = `translateX(${clamped}px)`;
    card.classList.toggle("swiping", clamped < -20);
    card.classList.toggle("swiping-delete-right", clamped > 20);
    const progress = String(Math.min(Math.abs(clamped) / SWIPE_DISTANCE, 1));
    for (const target of [card, actionShell]) {
      if (!target) {
        continue;
      }
      target.style.setProperty("--swipe-progress", progress);
      target.style.setProperty("--swipe-delete-right-progress", progress);
      target.style.setProperty("--swipe-skip-progress", progress);
      target.style.setProperty("--wf-editor-delete-progress", progress);
    }
    if (event.cancelable) {
      event.preventDefault();
    }
  }, { passive: false });

  card.addEventListener("touchend", () => {
    const direction = isDragging && Math.abs(deltaX) > SWIPE_THRESHOLD
      ? (deltaX < 0 ? "left" : "right")
      : null;
    card.style.transform = "";
    card.classList.remove("swiping", "swiping-delete-right");
    for (const target of [card, actionShell]) {
      if (!target) {
        continue;
      }
      target.style.setProperty("--swipe-progress", "0");
      target.style.setProperty("--swipe-delete-right-progress", "0");
      target.style.setProperty("--swipe-skip-progress", "0");
      target.style.setProperty("--wf-editor-delete-progress", "0");
    }
    if (direction) {
      suppressNextCardClick(card);
      onSwipe(direction);
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

export function attachSwipeGestures(card, { onLeft, onRight }) {
  attachSwipeTracking(card, (direction) => {
    if (direction === "left") {
      onLeft();
      return;
    }
    onRight();
  });
}

async function setStatusForEntries(entryIds, status) {
  const ids = normalizeEntryIds(entryIds);
  if (ids.length === 0) {
    return;
  }
  if (typeof _setStatusMany === "function") {
    await _setStatusMany(ids, status);
    return;
  }
  for (const entryId of ids) {
    await _setStatus(entryId, status);
  }
}

async function deleteEntries(entryIds) {
  const ids = normalizeEntryIds(entryIds);
  if (ids.length === 0) {
    return;
  }
  if (typeof _deleteEntries === "function") {
    await _deleteEntries(ids);
    return;
  }
  for (const entryId of ids) {
    await _deleteEntry(entryId);
  }
}

export function attachSwipeRightDeleteGesture(card, entryIds) {
  attachSwipeGestures(card, {
    onLeft: () => {},
    onRight: () => {
      _run(() => deleteEntries(entryIds));
    },
  });
}

export function attachRestoreToRemainingClick(card, entryIds) {
  card.addEventListener("click", () => {
    if (consumeSuppressedCardClick(card)) {
      return;
    }
    _run(() => setStatusForEntries(entryIds, "remaining"));
  });
}

export function attachRemainingCardGestures(card, entryIds) {
  attachSwipeTracking(card, (direction) => {
    if (direction === "left") {
      _run(() => setStatusForEntries(entryIds, "skipped"));
    }
  });
  card.addEventListener("click", () => {
    if (consumeSuppressedCardClick(card)) {
      return;
    }
    _run(() => setStatusForEntries(entryIds, "completed"));
  });
}

export function attachCompletedCardGestures(card, entryIds) {
  attachSwipeGestures(card, {
    onLeft: () => {
      _run(() => setStatusForEntries(entryIds, "skipped"));
    },
    onRight: () => {
      _run(() => deleteEntries(entryIds));
    },
  });
  card.addEventListener("click", () => {
    if (consumeSuppressedCardClick(card)) {
      return;
    }
    _run(() => setStatusForEntries(entryIds, "remaining"));
  });
}

export function createCard(item, mode) {
  const cardShell = document.createElement("div");
  cardShell.className = `shop-card-shell shop-card-status-${mode}`;
  const card = document.createElement("div");
  card.className = "shop-card";
  cardShell.appendChild(card);

  const entryIds = normalizeEntryIds(item.entry_ids && item.entry_ids.length ? item.entry_ids : item.id);
  const unitPart = item.unit ? ` ${item.unit}` : "";
  const quantityText = `${item.amount}${unitPart}`.trim();
  const amountLines = Array.isArray(item.amount_lines) && item.amount_lines.length > 0
    ? item.amount_lines
    : [quantityText];
  const amountMarkup = amountLines
    .map((line) => `<span class="shop-item-amount-line">${escapeAttr(line)}</span>`)
    .join("");

  const deleteRightHint = `
    <div class="shop-swipe-delete-right-hint" aria-hidden="true">
      <span class="shop-swipe-delete-right-icon">×</span>
      <span class="shop-swipe-delete-right-label">Delete</span>
    </div>`;
  const skipHint = mode
    ? `
    <div class="shop-swipe-skip-hint" aria-hidden="true">
      <span class="shop-swipe-skip-icon">\u22ef</span>
      <span class="shop-swipe-skip-label">Postpone</span>
    </div>`
    : "";

  card.innerHTML = `
    ${deleteRightHint}
    ${skipHint}
    <div class="shop-card-head">
      <div class="shop-card-name-wrap">
        <strong class="shop-item-name">${escapeAttr(item.name)}</strong>
        <span class="shop-item-category muted">${escapeAttr(item.ingredient_type)}</span>
      </div>
      <div class="shop-item-amount muted">${amountMarkup}</div>
    </div>
  `;
  for (const hint of card.querySelectorAll(".shop-swipe-delete-right-hint, .shop-swipe-skip-hint")) {
    cardShell.appendChild(hint);
  }

  if (mode === "remaining") {
    attachRemainingCardGestures(card, entryIds);
  } else if (mode === "completed") {
    attachCompletedCardGestures(card, entryIds);
  } else {
    attachRestoreToRemainingClick(card, entryIds);
  }
  attachSwipeRightDeleteGesture(card, entryIds);

  return cardShell;
}
