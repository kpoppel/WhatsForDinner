/** Minimal runtime assertions for server payloads consumed by UI commands. */
/** Reject malformed API payloads at the boundary before state mutation. */
export function assertObject(value, contextLabel) {
  if (!value || typeof value !== "object") {
    throw new Error(`${contextLabel} must be an object.`);
  }
}

/** Assert that a validated object contains every required contract field. */
export function assertRequiredFields(value, fields, contextLabel) {
  assertObject(value, contextLabel);
  for (const field of fields) {
    if (!(field in value)) {
      throw new Error(`${contextLabel} missing required field: ${field}`);
    }
  }
}
