/* The only module that knows the owner endpoints, all under /api/v1/platform/ and enforced by the backend (platform owner only).
 * A 404/405/501 is reported as "not_available" so a page can say so honestly (for example on an older server) instead of
 * showing fake data. No mock data lives here. */
import { api, ApiError } from "../../shared/js/api.js";

export const NOT_AVAILABLE = "not_available";
const MISSING = new Set([404, 405, 501]);

export const isNotAvailable = (err) => err instanceof ApiError && err.code === NOT_AVAILABLE;

/** "?a=1&b=2" from an object, skipping empty values. Returns "" when nothing is set. */
export function buildQuery(params = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && String(value).trim() !== "") query.set(key, String(value).trim());
  }
  const text = query.toString();
  return text ? `?${text}` : "";
}

async function call(run) {
  try {
    return await run();
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) window.dispatchEvent(new Event("owner:unauthenticated"));
    if (err instanceof ApiError && MISSING.has(err.status)) {
      throw new ApiError({ status: err.status, code: NOT_AVAILABLE, message: "This server doesn't provide this owner endpoint yet." });
    }
    throw err;
  }
}

const P = "/platform";
export const platform = {
  me: (o) => call(() => api.get(`${P}/me/`, o)),
  overview: (range, o) => call(() => api.get(`${P}/overview/${buildQuery({ range })}`, o)),
  usage: (params, o) => call(() => api.get(`${P}/usage/${buildQuery(params)}`, o)),
  list: (name, query, o) => call(() => api.get(`${P}/${name}/${query ?? ""}`, o)), // customers, credentials, subscriptions, payments, audit
  detail: (name, id, o) => call(() => api.get(`${P}/${name}/${encodeURIComponent(id)}/`, o)),
  action: (name, id, action, body) => call(() => api.post(`${P}/${name}/${encodeURIComponent(id)}/${action}/`, body ?? {})),
  create: (name, body) => call(() => api.post(`${P}/${name}/`, body)),
  update: (name, id, body) => call(() => api.patch(`${P}/${name}/${encodeURIComponent(id)}/`, body)),
  settings: (o) => call(() => api.get(`${P}/settings/`, o)),
  remove: (name, id) => call(() => api.delete(`${P}/${name}/${encodeURIComponent(id)}/`)),
  notifications: (o) => call(() => api.get(`${P}/notifications/`, o)),
  markNotificationsRead: (ids) => call(() => api.post(`${P}/notifications/read/`, ids ? { ids } : {})),
  saveSettings: (body) => call(() => api.patch(`${P}/settings/`, body)),
};

/** Existing endpoint (connected): change the signed-in administrator's password. */
export const changePassword = (current_password, new_password) => api.post("/auth/password/", { current_password, new_password });
