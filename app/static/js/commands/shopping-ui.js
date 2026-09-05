import { state } from "../state.js";

export function toggleShoppingSectionCollapsed(key) {
  state.collapsedSections[key] = !state.collapsedSections[key];
}