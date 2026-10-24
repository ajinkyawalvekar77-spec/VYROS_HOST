import { describe, expect, it } from "vitest";
import { backtestInput, planInputIssue } from "./workflowInputs";

const planningData = {
  as_of: "2026-10-01",
  demand_history: [{ demand_date: "2026-10-01" }],
  inventory_batches: [{ batch_id: "B-1" }],
  lanes: [{ warehouse_id: "W-1" }],
  transport_costs: [{ unit_transport_cost: 1 }],
  capacities: [{ capacity_units: 10 }],
  evaluation_actuals: [
    { demand_date: "2026-10-02", quantity: 2 },
    { demand_date: "2026-10-03", quantity: 3 },
    { demand_date: "2026-10-04", quantity: 4 },
  ],
};

describe("workflow input requirements", () => {
  it("explains which planning tables are missing for a demand-only upload", () => {
    expect(planInputIssue({ demand_history: [{}] })).toContain(
      "inventory_batches, lanes, transport_costs",
    );
    expect(planInputIssue(planningData)).toBeNull();
  });

  it("selects exactly the held-out dates requested for a backtest", () => {
    const result = backtestInput(planningData, 2);

    expect(result.issue).toBeNull();
    expect(result.origin).toBe("2026-10-01");
    expect(result.actuals).toEqual(planningData.evaluation_actuals.slice(0, 2));
  });

  it("rejects incomplete actual windows and missing evaluation tables", () => {
    expect(backtestInput(planningData, 4).issue).toContain("held-out evaluation_actuals");
    expect(backtestInput({ demand_history: [{}] }, 7).issue).toContain("inventory_batches");
  });

  it("derives the chronological origin from the latest history date if absent", () => {
    const { as_of: _asOf, ...data } = planningData;
    const result = backtestInput({
      ...data,
      demand_history: [{ demand_date: "2026-09-30" }],
      evaluation_actuals: [
        { demand_date: "2026-10-01", quantity: 2 },
        { demand_date: "2026-10-02", quantity: 3 },
      ],
    }, 2);

    expect(result.origin).toBe("2026-09-30");
    expect(result.issue).toBeNull();
  });
});
