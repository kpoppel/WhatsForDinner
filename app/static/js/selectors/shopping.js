import { state } from "../state.js";

export function shoppingItems() {
  return Object.values(state.itemsById)
    .filter((item) => item && item.id !== undefined && item.id !== null);
}

export function shoppingItem(entryId) {
  return state.itemsById[String(entryId)] || null;
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