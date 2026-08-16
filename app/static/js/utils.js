export function escapeAttr(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

export function shoppingItemId(value) {
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
}
