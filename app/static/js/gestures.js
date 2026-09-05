/** Translate Shopping Mode pointer gestures into injected domain actions. */
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
      _run(() => deleteEntries(entryIds));
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

export function attachRestoreToRemainingClick(card, entryIds) {
  card.addEventListener("click", () => {
    if (consumeSuppressedCardClick(card)) {
      return;
    }
    _run(() => setStatusForEntries(entryIds, "remaining"));
  });
}

export function attachRemainingCardGestures(card, entryIds) {
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
      _run(() => setStatusForEntries(entryIds, "skipped"));
    }
    isDragging = false;
    deltaX = 0;
  });

  card.addEventListener("click", () => {
    if (consumeSuppressedCardClick(card)) {
      return;
    }
    _run(() => setStatusForEntries(entryIds, "completed"));
  });
}

export function attachCompletedCardGestures(card, entryIds) {
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
      _run(() => deleteEntries(entryIds));
    }
    isDragging = false;
    deltaX = 0;
  });

  card.addEventListener("click", () => {
    if (consumeSuppressedCardClick(card)) {
      return;
    }
    _run(() => setStatusForEntries(entryIds, "remaining"));
  });
}

export function createCard(item, mode) {
  const card = document.createElement("div");
  card.className = "shop-card";

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
      <div class="shop-item-amount muted">${amountMarkup}</div>
    </div>
  `;

  if (mode === "remaining") {
    attachRemainingCardGestures(card, entryIds);
  } else if (mode === "completed") {
    attachCompletedCardGestures(card, entryIds);
  } else {
    attachRestoreToRemainingClick(card, entryIds);
  }
  attachSwipeRightDeleteGesture(card, entryIds);

  return card;
}
