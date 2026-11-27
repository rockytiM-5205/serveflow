/* Small fetch wrapper for the ServeFlow API.
 * - JSON in and out; every failure becomes an ApiError with the backend's error envelope.
 * - Sends the CSRF token (from the csrftoken cookie) on unsafe methods.
 * - Same-origin cookies only (credentials: "same-origin"); nothing is stored in JS.
 * - Timeout and caller cancellation via AbortController.
 */
import { config } from "./config.js";

export class ApiError extends Error {
  constructor({ status = 0, code = "error", message = "Something went wrong.", details = {}, retryAfter = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status; // 0 when the server was never reached
    this.code = code;
    this.details = details;
    this.retryAfter = retryAfter; // seconds, from Retry-After (429)
  }
}

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

function readCookie(name) {
  const prefix = `${name}=`;
  for (const part of document.cookie.split("; ")) {
    if (part.startsWith(prefix)) return decodeURIComponent(part.slice(prefix.length));
  }
  return null;
}

/** The first human-readable sentence inside a validation error's details (a string, a list of strings, or fields holding those). */
function firstDetail(details) {
  if (typeof details === "string") return details;
  if (Array.isArray(details)) {
    for (const item of details) { const found = firstDetail(item); if (found) return found; }
    return "";
  }
  if (details && typeof details === "object") {
    for (const value of Object.values(details)) { const found = firstDetail(value); if (found) return found; }
  }
  return "";
}

function errorFrom(response, data) {
  const envelope = data && typeof data === "object" ? data.error : null;
  const retry = Number.parseInt(response.headers.get("Retry-After") ?? "", 10);
  // "The request was invalid." tells a restaurant nothing; the reason (for example "Add your bank details first") is in the details.
  const reason = envelope?.code === "validation_error" ? firstDetail(envelope?.details) : "";
  return new ApiError({
    status: response.status,
    code: envelope?.code ?? "http_error",
    message: reason || (envelope?.message ?? `Request failed (${response.status}).`),
    details: envelope?.details ?? {},
    retryAfter: Number.isFinite(retry) ? retry : null,
  });
}

/** Reads that fail to connect (or get a 502/503/504 from a busy or restarting server) are tried again quietly before the person
 * sees an error. Only reads: a write is never repeated behind the person's back. Tests set delaysMs to [] to skip the waiting. */
export const retryPolicy = { delaysMs: [400, 1500, 4000, 8000] }; // long enough for a sleeping free-tier server to wake up
const transient = (err) => err instanceof ApiError && (err.code === "network_error" || err.code === "timeout" || [502, 503, 504].includes(err.status));
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export async function request(path, options = {}) {
  if ((options.method ?? "GET") !== "GET") return requestOnce(path, options);
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await requestOnce(path, options);
    } catch (err) {
      if (!transient(err) || attempt >= retryPolicy.delaysMs.length || options.signal?.aborted) throw err;
      await pause(retryPolicy.delaysMs[attempt]);
    }
  }
}

async function requestOnce(path, { method = "GET", body, signal, timeoutMs = config.requestTimeoutMs, headers: extraHeaders = {} } = {}) {
  const headers = { Accept: "application/json", ...extraHeaders };
  const init = { method, headers, credentials: "same-origin", cache: "no-store" };
  if (body instanceof FormData) {
    init.body = body; // the browser sets the multipart Content-Type and boundary itself
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  if (!SAFE_METHODS.has(method)) {
    const token = readCookie("csrftoken");
    if (token) headers["X-CSRFToken"] = token;
  }

  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const onCallerAbort = () => controller.abort();
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener("abort", onCallerAbort, { once: true });
  }
  init.signal = controller.signal;

  try {
    const response = await fetch(config.apiBaseUrl + path, init);
    if (response.status === 204) return null;
    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = null;
      }
    }
    if (!response.ok) {
      const failure = errorFrom(response, data);
      if (failure.status === 402 && failure.code === "subscription_inactive" && typeof window !== "undefined") {
        window.dispatchEvent(new Event("serveflow:subscription-ended"));
      }
      throw failure;
    }
    if (data === null) {
      // 2xx without JSON usually means the base URL points at the wrong server.
      throw new ApiError({ status: response.status, code: "invalid_response", message: "The server sent an unexpected response." });
    }
    return data;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (timedOut) throw new ApiError({ code: "timeout", message: "The server is taking a while to respond. Please try again in a moment." });
    if (signal?.aborted) throw err; // the caller cancelled; let them see the AbortError
    throw new ApiError({ code: "network_error", message: "Can't reach the server. Check your connection and try again." });
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onCallerAbort);
  }
}

export const api = {
  get: (path, options) => request(path, { ...options, method: "GET" }),
  post: (path, body, options) => request(path, { ...options, method: "POST", body }),
  put: (path, body, options) => request(path, { ...options, method: "PUT", body }),
  patch: (path, body, options) => request(path, { ...options, method: "PATCH", body }),
  upload: (path, formData, options) => request(path, { ...options, method: "POST", body: formData }),
  delete: (path, options) => request(path, { ...options, method: "DELETE" }),
};
