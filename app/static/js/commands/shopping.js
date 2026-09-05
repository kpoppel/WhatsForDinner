import { apiUpload } from "../api.js";
import { queueCreateChange, queueDeleteChange, queueUpdateChange } from "../state.js";
import {
  deleteEntries,
  deleteEntry,
  refresh,
  refreshAndSyncIfNeeded,
  run,
  setStatus,
  setStatusMany,
  syncPending,
} from "../sync.js";

export function createShoppingItem(payload) {
  queueCreateChange(payload);
}

export function deleteShoppingItem(entryId) {
  queueDeleteChange(entryId);
}

export function updateShoppingItem(entryId, patch) {
  queueUpdateChange(entryId, patch);
}

export async function uploadShoppingOcr(formData) {
  return await apiUpload("/shopping-list/ocr", formData);
}

export const runShoppingAction = run;
export const refreshShopping = refresh;
export const syncShopping = syncPending;
export const refreshShoppingAndSync = refreshAndSyncIfNeeded;
export const setShoppingStatus = setStatus;
export const setShoppingStatusMany = setStatusMany;
export const deleteShoppingEntries = deleteEntries;
export const deleteShoppingEntry = deleteEntry;