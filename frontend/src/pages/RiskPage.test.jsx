import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import RiskPage from "./RiskPage";

const { api, useApp } = vi.hoisted(() => ({
  api: {
    risk: vi.fn(),
    riskForDataset: vi.fn(),
  },
  useApp: vi.fn(),
}));

vi.mock("../services/api", () => ({ api }));
vi.mock("../context/AppContext", () => ({ useApp }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("dataset-specific risk indicators", () => {
  it("uses the active dataset instead of a stale backtest and sends only API fields", async () => {
    useApp.mockReturnValue({
      demoData: {
        as_of: "2026-10-20",
        synthetic: false,
        seed: 12,
        demand_history: [{ sku_id: "SKU-1", destination_id: "DEST-1", demand_date: "2026-10-20", quantity: 4 }],
        generation_rules: { internal: "metadata" },
        evaluation_actuals: [{ internal: "future data" }],
      },
      runs: [{ operation: "backtest", run_id: "stale-backtest" }],
      backtest: { run_id: "stale-backtest" },
      notify: vi.fn(),
    });
    api.riskForDataset.mockResolvedValue({
      dataset_id: "a".repeat(64),
      synthetic: false,
      risk_score: null,
      indicator_scope: "SKU-level forecast uncertainty; inventory risk unavailable",
      indicators: [],
      unavailable_indicators: [],
      limitations: [],
    });

    render(<RiskPage />);

    await waitFor(() => expect(api.riskForDataset).toHaveBeenCalledWith({
      as_of: "2026-10-20",
      synthetic: false,
      seed: 12,
      demand_history: [{ sku_id: "SKU-1", destination_id: "DEST-1", demand_date: "2026-10-20", quantity: 4 }],
    }, { signal: expect.any(AbortSignal) }));
    expect(api.risk).not.toHaveBeenCalled();
    expect(await screen.findByText("UPLOADED DATASET INDICATORS")).toBeInTheDocument();
  });
});
