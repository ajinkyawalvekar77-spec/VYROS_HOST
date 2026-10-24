import { afterEach, describe, expect, it, vi } from "vitest";
import { auth } from "./auth";
import { api } from "./api";

vi.mock("./auth", () => ({
  auth: { getIdToken: vi.fn() },
}));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("backend API client", () => {
  it("sends forecast requests as JSON and returns the backend result", async () => {
    const payload = { demand_history: [{ sku_id: "SKU-1", quantity: 12 }] };
    const result = { run_id: "run-123", status: "succeeded", forecasts: [] };
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => result });
    vi.stubGlobal("fetch", fetch);
    auth.getIdToken.mockResolvedValue("test-id-token");

    await expect(api.forecast(payload)).resolves.toEqual(result);
    expect(fetch).toHaveBeenCalledWith(
      "/api/forecast",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(payload),
        headers: expect.objectContaining({
          "Content-Type": "application/json",
        }),
      }),
    );
    expect(fetch.mock.calls[0][1].headers.Authorization).toMatch(/^Bearer .+/);
  });

  it("preserves structured backend errors and failed run IDs", async () => {
    const response = {
      ok: false,
      status: 422,
      json: async () => ({
        error: { code: "invalid_dataset", message: "Dataset validation failed.", details: { field: "demand_history" } },
      }),
      headers: { get: (name) => (name.toLowerCase() === "x-run-id" ? "run-failed-123" : null) },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    auth.getIdToken.mockResolvedValue("test-id-token");

    await expect(api.plan({ demand_history: [] })).rejects.toMatchObject({
      name: "ApiError",
      status: 422,
      code: "invalid_dataset",
      message: "Dataset validation failed.",
      runId: "run-failed-123",
    });
  });

  it("retries a protected request once with a refreshed bearer token", async () => {
    const expired = { ok: false, status: 401, json: async () => ({}) };
    const success = { ok: true, json: async () => ({ status: "valid" }) };
    const fetch = vi.fn().mockResolvedValueOnce(expired).mockResolvedValueOnce(success);
    vi.stubGlobal("fetch", fetch);
    auth.getIdToken.mockResolvedValueOnce("expired-token").mockResolvedValueOnce("refreshed-token");

    await expect(api.validateData({ demand_history: [] })).resolves.toEqual({ status: "valid" });
    expect(auth.getIdToken).toHaveBeenNthCalledWith(1, { forceRefresh: false });
    expect(auth.getIdToken).toHaveBeenNthCalledWith(2, { forceRefresh: true });
    expect(fetch.mock.calls[1][1].headers.Authorization).toMatch(/^Bearer .+/);
  });

  it("does not send protected requests while sign-in is disabled", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    auth.getIdToken.mockRejectedValue(Object.assign(
      new Error("Authentication is temporarily unavailable."),
      { code: "auth/temporarily-disabled" },
    ));

    await expect(api.forecast({ demand_history: [] })).rejects.toMatchObject({
      name: "ApiError",
      status: 503,
      code: "authentication_temporarily_disabled",
    });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not attach an identity token to public health or demo-data requests", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "running" }) });
    vi.stubGlobal("fetch", fetch);

    await api.getHealth();
    await api.getDemoData({ seed: 42, profile: "compact" });
    expect(auth.getIdToken).not.toHaveBeenCalled();
    expect(fetch.mock.calls.every(([, options]) => !options.headers.Authorization)).toBe(true);
  });
});
