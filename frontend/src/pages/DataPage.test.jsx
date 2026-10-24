import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../context/AuthContext";
import { AppProvider } from "../context/AppContext";
import DataPage from "./DataPage";

const { api } = vi.hoisted(() => ({
  api: {
    forecast: vi.fn(),
    getDemoData: vi.fn(),
    validateData: vi.fn(),
  },
}));

vi.mock("../services/api", () => ({ api }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderDataPage() {
  return render(
    <AuthProvider>
      <AppProvider>
        <DataPage />
      </AppProvider>
    </AuthProvider>,
  );
}

describe("uploaded datasets", () => {
  it("sends uploaded CSV demand history to the backend and renders its forecast", async () => {
    const forecast = {
      run_id: "forecast-run",
      model_name: "moving_average_28",
      fallback_used: false,
      forecasts: [{
        forecast_date: "2026-10-21",
        sku_id: "SKU-1",
        destination_id: "DEST-1",
        point_forecast: 12,
      }],
    };
    api.validateData.mockResolvedValue({
      validation_scope: "demand_only",
      valid: true,
      error_count: 0,
      warning_count: 0,
      tables: { demand_history: { valid: true, row_count: 1 } },
      findings: [],
    });
    api.forecast.mockResolvedValue(forecast);
    renderDataPage();

    const file = new File(
      ["sku_id,destination_id,demand_date,quantity\nSKU-1,DEST-1,2026-10-20,10\n"],
      "demand.csv",
      { type: "text/csv" },
    );
    file.text = vi.fn().mockResolvedValue(
      "sku_id,destination_id,demand_date,quantity\nSKU-1,DEST-1,2026-10-20,10\n",
    );
    const input = document.querySelector('input[type="file"]');

    await act(async () => {
      fireEvent.change(input, { target: { files: [file] } });
    });

    await waitFor(() => expect(api.validateData).toHaveBeenCalledWith({
      validation_scope: "demand_only",
      demand_history: [{
        sku_id: "SKU-1",
        destination_id: "DEST-1",
        demand_date: "2026-10-20",
        quantity: 10,
      }],
      synthetic: false,
    }));
    expect(api.forecast).toHaveBeenCalledWith({
      demand_history: [{
        sku_id: "SKU-1",
        destination_id: "DEST-1",
        demand_date: "2026-10-20",
        quantity: 10,
      }],
      origin: undefined,
      horizon_days: 7,
      synthetic: false,
      seed: undefined,
    });
    expect(await screen.findByRole("heading", { name: "Backend forecast" })).toBeInTheDocument();
    expect(screen.getByText(/1 predictions · moving_average_28/)).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("does not call the forecast API for a malformed CSV", async () => {
    renderDataPage();
    const malformedCsv = "not,a,demand,csv\na,b,c,d";
    const file = new File([malformedCsv], "bad.csv", { type: "text/csv" });
    file.text = vi.fn().mockResolvedValue(malformedCsv);

    await act(async () => {
      fireEvent.change(document.querySelector('input[type="file"]'), { target: { files: [file] } });
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("CSV columns must be exactly");
    expect(api.forecast).not.toHaveBeenCalled();
  });

  it("does not forecast CSV data rejected by backend validation", async () => {
    api.validateData.mockResolvedValue({
      validation_scope: "demand_only",
      valid: false,
      error_count: 1,
      warning_count: 0,
      tables: { demand_history: { valid: false, row_count: 1 } },
      findings: [{
        severity: "error",
        table: "demand_history",
        row: 0,
        field: null,
        rule: "duplicate_key",
        message: "Duplicate demand-history records are not allowed.",
      }],
    });
    renderDataPage();
    const csv = "sku_id,destination_id,demand_date,quantity\nSKU-1,DEST-1,2026-10-20,10\nSKU-1,DEST-1,2026-10-20,12\n";
    const file = new File([csv], "demand.csv", { type: "text/csv" });
    file.text = vi.fn().mockResolvedValue(csv);

    await act(async () => {
      fireEvent.change(document.querySelector('input[type="file"]'), { target: { files: [file] } });
    });

    expect(await screen.findByText("Blocking findings detected")).toBeInTheDocument();
    expect(screen.getByText("Duplicate demand-history records are not allowed.")).toBeInTheDocument();
    expect(api.forecast).not.toHaveBeenCalled();
  });
});
