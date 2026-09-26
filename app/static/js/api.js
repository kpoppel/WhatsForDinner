import { setShoppingApiReachable, state } from "./state.js";

const apiPrefix = window.WFD_API_PREFIX;

// Every request is time-boxed: on a foreign network the server address is often
// black-holed, so an unbounded fetch would hang for the OS TCP timeout instead
// of letting the app fall back to offline mode.
const DEFAULT_TIMEOUT_MS = 8000;
const HEALTH_TIMEOUT_MS = 4000;
const UPLOAD_TIMEOUT_MS = 120000;
const CHAT_TIMEOUT_MS = 60000;

// Gateway-level failures mean the app server is not answering, which is an
// availability problem rather than a request the server rejected on purpose.
const UNREACHABLE_STATUSES = new Set([502, 503, 504]);

/**
 * Raised when the API could not be contacted at all: no network, wrong network,
 * captive-portal interception, request timeout, or an unavailable gateway.
 * Distinct from a plain Error, which signals a server-side rejection of a
 * request that did reach the API.
 */
export class ApiUnreachableError extends Error {
  constructor(message, cause) {
    super(message);
    this.name = "ApiUnreachableError";
    this.cause = cause;
  }
}

export function isApiUnreachableError(error) {
  return error instanceof ApiUnreachableError;
}

function publishApiReachability(value) {
  const previous = state.apiReachable;
  setShoppingApiReachable(value);
  if (previous !== Boolean(value)) {
    window.dispatchEvent(new CustomEvent("wfd:api-reachability-changed"));
  }
}

/**
 * Captive portals and unrelated devices on a foreign LAN answer with their own
 * HTML page and a 200 status, so only a JSON content type proves that the
 * response actually came from this API.
 */
function isJsonResponse(response) {
  const contentType = response.headers.get("content-type");
  if (typeof contentType !== "string") {
    return false;
  }
  return contentType.toLowerCase().includes("application/json");
}

/**
 * Perform one API call, translating transport-level outcomes into reachability
 * state and ApiUnreachableError, and server rejections into plain Error.
 */
async function request(path, options, timeoutMs) {
  let response;
  const { signal, ...fetchOptions } = options;
  try {
    response = await fetch(`${apiPrefix}${path}`, {
      ...fetchOptions,
      signal: AbortSignal.any([AbortSignal.timeout(timeoutMs), ...(signal ? [signal] : [])]),
    });
  } catch (error) {
    if (signal && signal.aborted) throw error;
    publishApiReachability(false);
    throw new ApiUnreachableError("The server could not be reached.", error);
  }

  if (UNREACHABLE_STATUSES.has(response.status)) {
    publishApiReachability(false);
    throw new ApiUnreachableError(`The server is unavailable (HTTP ${response.status}).`);
  }

  if (!isJsonResponse(response)) {
    publishApiReachability(false);
    throw new ApiUnreachableError("The response did not come from this API.");
  }

  let data;
  try {
    data = await response.json();
  } catch (error) {
    if (signal && signal.aborted) throw error;
    publishApiReachability(false);
    throw new ApiUnreachableError("The server returned a malformed response.", error);
  }

  publishApiReachability(true);
  if (!response.ok) {
    throw new Error(data.detail || JSON.stringify(data));
  }
  return data;
}

export async function api(path, options = {}) {
  return await request(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  }, DEFAULT_TIMEOUT_MS);
}

export async function apiUpload(path, formData) {
  return await request(path, {
    method: "POST",
    body: formData,
  }, UPLOAD_TIMEOUT_MS);
}

export async function apiChat(path, options) {
  return await request(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  }, CHAT_TIMEOUT_MS);
}

export async function health() {
  return await request("/health", { cache: "no-store" }, HEALTH_TIMEOUT_MS);
}
