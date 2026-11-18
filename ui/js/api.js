// Calls to the two services from the browser (Assignment 2 §1a, §7.5).
//
// - Their addresses come from config.js, never from this code.
// - The sign-in token is kept in localStorage and sent as "Authorization: Bearer <token>".
// - Every call has a timeout, so a request can never hang the page.
// - A cold start on Azure (the container starting, the database resuming from pause) answers 503 or
//   nothing at all for up to about a minute. Those calls are retried with growing waits while a banner
//   says "starting up"; after the last try the banner offers a Retry button. A blank page never happens.
// - A 503 that the services send on purpose (the other service is down) is not retried: the page shows
//   its message, because waiting will not help.
"use strict";

const Api = (() => {
  const TOKEN_KEY = "float.token";
  const TIMEOUT_MS = 20000;
  const RETRY_WAITS_MS = [3000, 8000, 15000, 25000]; // about a minute in total, enough for the database to resume
  const DESIGNED = new Set(["Households unavailable", "Ledger unavailable"]);

  class ApiError extends Error {
    constructor(status, problem) {
      super(problem.detail || problem.title || `HTTP ${status}`);
      this.status = status;
      this.problem = problem;
    }
  }

  function token() {
    try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
  }

  function setToken(value) {
    try {
      if (value) localStorage.setItem(TOKEN_KEY, value);
      else localStorage.removeItem(TOKEN_KEY);
    } catch { /* private mode: the user signs in again next time */ }
  }

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function base(service) {
    const config = window.FLOAT_CONFIG || {};
    return service === "households" ? config.householdsUrl : config.personalUrl;
  }

  async function readBody(response) {
    const type = response.headers.get("content-type") || "";
    if (response.status === 204) return null;
    if (type.includes("json")) return response.json();
    const text = await response.text();
    return { title: `HTTP ${response.status}`, detail: text.slice(0, 200) };
  }

  async function call(service, method, path, body, { auth = true, headers = {} } = {}) {
    const request = { method, headers: { ...headers } };
    if (body !== undefined) {
      request.headers["Content-Type"] = "application/json";
      request.body = JSON.stringify(body);
    }
    if (auth && token()) request.headers.Authorization = `Bearer ${token()}`;
    for (let attempt = 0; ; attempt += 1) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
      let response = null;
      try {
        response = await fetch(`${base(service)}/api/v1${path}`, { ...request, signal: controller.signal });
      } catch {
        response = null; // timeout, connection refused, or a CORS failure while the app is starting
      } finally {
        clearTimeout(timer);
      }
      const data = response ? await readBody(response).catch(() => ({})) : null;
      const startingUp = response === null || (response.status === 503 && !DESIGNED.has(data?.title))
        || response.status === 502 || response.status === 504;
      if (startingUp) {
        if (attempt < RETRY_WAITS_MS.length) {
          UI.banner("Float is starting up (the database may be waking from a pause). Retrying…");
          await sleep(RETRY_WAITS_MS[attempt]);
          continue;
        }
        UI.banner("Float is still starting. Wait a minute, then try again.", { tone: "warning", retry: true });
        throw new ApiError(503, { title: "Starting up", detail: "Float is still starting." });
      }
      UI.clearBanner();
      if (response.status === 401 && auth) {
        setToken(null);
        location.replace("index.html");
        throw new ApiError(401, data);
      }
      if (response.status === 409 && data?.title === "Setup needed" && !location.pathname.endsWith("setup.html")) {
        location.replace("setup.html");
        throw new ApiError(409, data);
      }
      if (!response.ok) throw new ApiError(response.status, data || {});
      return data;
    }
  }

  // The signed-in user, or a redirect to the login page.
  async function me() {
    if (!token()) {
      location.replace("index.html");
      return new Promise(() => {});
    }
    return call("personal", "GET", "/me");
  }

  async function logout() {
    try { await call("personal", "POST", "/auth/logout"); } catch { /* signed out locally either way */ }
    setToken(null);
    location.replace("index.html");
  }

  return {
    ApiError, token, setToken, me, logout,
    personal: (method, path, body, options) => call("personal", method, path, body, options),
    households: (method, path, body, options) => call("households", method, path, body, options),
  };
})();
