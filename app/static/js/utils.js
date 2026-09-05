/** Small normalization and escaping helpers shared by frontend boundaries. */
/** Escape text before inserting it into an HTML attribute. */
export function escapeAttr(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

/** Normalize remote and temporary shopping IDs to integers or null. */
export function shoppingItemId(value) {
  const id = Number(value);
  return Number.isInteger(id) && id !== 0 ? id : null;
}
