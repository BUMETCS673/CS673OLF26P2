/**
 * The one place that calls fetch() — WS3 (Duc).
 *
 * Every request in the app goes through here (rule 2 in ITERATION_1_PLAN.md), so no
 * component ever writes a URL inline. WS4 uses this too.
 *
 * What it takes care of:
 *   - the /api prefix, which the Vite dev server proxies to Flask (decision D4), so the
 *     browser only ever sees one origin and the session cookie just works
 *   - `credentials: "include"`, so that cookie actually travels
 *   - turning the contract's error shape into a thrown `ApiError` carrying `code`,
 *     `message` and (on a 422) `field`
 *
 * Callers switch on `err.code`, never on `err.message` — the code table in the contract
 * is closed, the wording isn't.
 */

const BASE = "/api";

export class ApiError extends Error {
  constructor(status, code, message, field) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.field = field;
  }
}

async function request(path, { method = "GET", body } = {}) {
  let response;

  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      // The session cookie is HttpOnly, so scripts can't read it -- the browser has to
      // be told to send it, and this is how.
      credentials: "include",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    // fetch() only rejects when the request never got an answer at all: the backend is
    // down, or the network is gone. Every HTTP status, including 500, resolves.
    throw new ApiError(0, "network_error", "Can't reach the server. Check your connection and try again.");
  }

  // 204 is the contract's answer for logout and delete, and it has no body at all --
  // calling response.json() on it throws.
  if (response.status === 204) {
    return null;
  }

  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      // A non-JSON body means something upstream answered instead of our API -- a proxy
      // error page, say. Handled as a failure below; on a 2xx it just isn't data.
      payload = null;
    }
  }

  if (!response.ok) {
    const error = payload?.error ?? {};
    throw new ApiError(
      response.status,
      error.code ?? "error",
      error.message ?? "Something went wrong. Please try again.",
      error.field,
    );
  }

  return payload;
}

export const get = (path) => request(path);
export const post = (path, body) => request(path, { method: "POST", body });
export const patch = (path, body) => request(path, { method: "PATCH", body });
export const del = (path) => request(path, { method: "DELETE" });
