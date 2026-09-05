/** Minimal runtime assertions for server payloads consumed by UI commands. */
export function assertObject(value, contextLabel) {
  if (!value || typeof value !== "object") {
    throw new Error(`${contextLabel} must be an object.`);
  }
}

export function assertRequiredFields(value, fields, contextLabel) {
  assertObject(value, contextLabel);
  for (const field of fields) {
    if (!(field in value)) {
      throw new Error(`${contextLabel} missing required field: ${field}`);
    }
  }
}
