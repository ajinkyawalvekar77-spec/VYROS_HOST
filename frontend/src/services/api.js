import { endpoints } from "./endpoints";
import { auth } from "./auth";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/+$/, "");
const DEFAULT_TIMEOUT_MS = 120_000;

function requiresAuthentication(path, method = "GET") {
  if (path === endpoints.health || path.startsWith(`${endpoints.demoData}?`) || path === endpoints.demoData) return false;
  if (path.startsWith("/api/runs/")) return true;
  if (path.startsWith(`${endpoints.risk}?`)) {
    return new URLSearchParams(path.split("?")[1]).has("run_id");
  }
  return method !== "GET" || path === endpoints.risk;
}

export class ApiError extends Error {
  constructor(message, { status = 0, code = "network_error", details = null, runId = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.runId = runId;
  }
}

async function request(path, { signal, timeoutMs = DEFAULT_TIMEOUT_MS, ...options } = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort("timeout"), timeoutMs);
  const abortFromCaller = () => controller.abort(signal?.reason);
  signal?.addEventListener("abort", abortFromCaller, { once: true });
  const protectedRequest = requiresAuthentication(path, options.method || "GET");

  try {
    const send = async (forceRefresh = false) => {
      const token = protectedRequest && !auth.localDevelopmentMode
        ? await auth.getIdToken({ forceRefresh })
        : null;
      return fetch(`${API_BASE}${path}`, {
        ...options,
        signal: controller.signal,
        headers: {
          ...(options.body instanceof FormData ? {} : { Accept: "application/json" }),
          ...options.headers,
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
    };
    let response = await send();
    if (response.status === 401 && protectedRequest) response = await send(true);
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      const error = body?.error;
      throw new ApiError(
        error?.message || `Request failed (${response.status}).`,
        {
          status: response.status,
          code: error?.code || "http_error",
          details: error?.details ?? null,
          runId: response.headers.get("x-run-id") || error?.details?.run_id || null,
        },
      );
    }
    return response;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error?.code === "auth/not-configured" || error?.code === "auth/not-authenticated") {
      throw new ApiError(error.message, {
        status: 401,
        code: error.code === "auth/not-configured" ? "authentication_not_configured" : "authentication_required",
      });
    }
    if (error?.code === "auth/temporarily-disabled") {
      throw new ApiError(error.message, {
        status: 503,
        code: "authentication_temporarily_disabled",
      });
    }
    if (controller.signal.aborted) {
      const timedOut = controller.signal.reason === "timeout";
      throw new ApiError(
        timedOut ? "The backend request timed out. Try again with a smaller dataset." : "The request was cancelled.",
        { code: timedOut ? "timeout" : "aborted" },
      );
    }
    throw new ApiError(
      "Could not reach the Optiqo backend. Check that FastAPI is running and the API URL is correct.",
      { code: "network_error" },
    );
  } finally {
    window.clearTimeout(timeout);
    signal?.removeEventListener("abort", abortFromCaller);
  }
}

async function jsonRequest(path, options = {}) {
  const response = await request(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  return response.json();
}

export const api = {
  getHealth: (options) => jsonRequest(endpoints.health, options),
  getDemoData: ({ seed = 42, profile = "compact", signal } = {}) =>
    jsonRequest(`${endpoints.demoData}?seed=${encodeURIComponent(seed)}&profile=${encodeURIComponent(profile)}`, { signal }),
  validateData: (payload, options = {}) =>
    jsonRequest(endpoints.validate, { ...options, method: "POST", body: payload }),
  forecast: (payload, options = {}) =>
    jsonRequest(endpoints.forecast, { ...options, method: "POST", body: payload }),
  plan: (payload, options = {}) =>
    jsonRequest(endpoints.plan, { ...options, method: "POST", body: payload }),
  risk: ({ seed = 42, runId, signal } = {}) => {
    const params = new URLSearchParams();
    if (runId) params.set("run_id", runId);
    else params.set("seed", String(seed));
    return jsonRequest(`${endpoints.risk}?${params}`, { signal });
  },
  riskForDataset: (payload, options = {}) =>
    jsonRequest(endpoints.riskDataset, { ...options, method: "POST", body: payload }),
  backtest: (payload, options = {}) =>
    jsonRequest(endpoints.backtest, { ...options, method: "POST", body: payload }),
  getRun: (runId, options) => jsonRequest(endpoints.run(runId), options),
  exportRun: async (runId, format = "json", options = {}) => {
    const response = await request(endpoints.exportRun(runId, format), options);
    return {
      blob: await response.blob(),
      filename:
        response.headers.get("content-disposition")?.match(/filename="([^"]+)"/)?.[1] ||
        `optiqo-run-${runId}.${format}`,
    };
  },
};

export function apiBaseLabel() {
  return API_BASE || "same origin (/api via Vite proxy in development)";
}
