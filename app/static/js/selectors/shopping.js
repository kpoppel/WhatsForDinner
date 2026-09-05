import { state } from "../state.js";

export function shoppingItems() {
  const items = Object.values(state.itemsById)
    .filter((item) => item && item.id !== undefined && item.id !== null);
  return structuredClone(items);
}

export function shoppingItem(entryId) {
  const item = state.itemsById[String(entryId)] || null;
  return structuredClone(item);
}

export function shoppingItemIds() {
  return Object.keys(state.itemsById);
}

export function shoppingItemsByStatus(status) {
  return shoppingItems()
    .filter((item) => item.status === status)
    .sort((left, right) => String(left.name).localeCompare(String(right.name)));
}

export function pendingShoppingChangeCount() {
  return state.pendingChanges.length;
}

export function shoppingApiReachable() {
  return state.apiReachable;
}

export function shoppingSectionCollapsed(key) {
  return Boolean(state.collapsedSections[key]);
}