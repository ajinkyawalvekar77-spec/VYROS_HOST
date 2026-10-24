import { afterEach, describe, expect, it, vi } from "vitest";
import { auth, authErrorMessage } from "./auth";

describe("temporarily disabled authentication adapter", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not perform direct authentication while the provider is disconnected", async () => {
    expect(auth.enabled).toBe(false);
    await expect(auth.signIn("user@example.com", "password"))
      .rejects.toMatchObject({ code: "auth/temporarily-disabled" });
  });

  it("explains why sign-in is unavailable", () => {
    expect(authErrorMessage({ code: "auth/temporarily-disabled" }))
      .toMatch(/firebase sign-in has been disconnected/i);
  });
});
