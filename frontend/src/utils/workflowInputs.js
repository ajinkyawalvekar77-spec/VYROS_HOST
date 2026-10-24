const PLAN_TABLES = ["demand_history", "inventory_batches", "lanes", "transport_costs"];
const BACKTEST_TABLES = [
  "demand_history",
  "inventory_batches",
  "lanes",
  "transport_costs",
  "capacities",
  "evaluation_actuals",
];

function missingTables(data, tables) {
  return tables.filter((table) => !Array.isArray(data?.[table]) || data[table].length === 0);
}

function isoDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value ?? ""));
  if (!match) return null;
  const date = new Date(`${match[1]}-${match[2]}-${match[3]}T00:00:00.000Z`);
  return Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== match[0]
    ? null
    : date;
}

function dateKey(date) {
  return date.toISOString().slice(0, 10);
}

export function planInputIssue(data) {
  const missing = missingTables(data, PLAN_TABLES);
  if (!missing.length) return null;
  return `Cannot create an allocation from this dataset yet. Missing required data: ${missing.join(", ")}. Upload a full JSON dataset with inventory, eligible lanes, and transport costs; demand-only CSV uploads support forecasting only.`;
}

export function backtestInput(data, evaluationDays) {
  const missing = missingTables(data, BACKTEST_TABLES);
  if (missing.length) {
    return {
      issue: `Cannot run a policy backtest from this dataset yet. Missing required data: ${missing.join(", ")}. Backtesting needs demand history, inventory, lanes, costs, capacities, and held-out evaluation_actuals. Upload a complete JSON dataset; demand-only CSV uploads support forecasting only.`,
      actuals: [],
      origin: null,
    };
  }

  const historyDates = data.demand_history.map((row) => isoDate(row.demand_date)).filter(Boolean);
  const origin = isoDate(data.as_of) || historyDates.reduce(
    (latest, date) => date > latest ? date : latest,
    null,
  );
  if (!origin) {
    return {
      issue: "The dataset needs a valid as_of date (or dated demand history) to define the chronological backtest boundary.",
      actuals: [],
      origin: null,
    };
  }

  const end = new Date(origin.getTime() + evaluationDays * 24 * 60 * 60 * 1000);
  const actuals = data.evaluation_actuals.filter((row) => {
    const date = isoDate(row.demand_date);
    return date && date > origin && date <= end;
  });
  const actualDates = new Set(actuals.map((row) => dateKey(isoDate(row.demand_date))));
  if (actualDates.size !== evaluationDays) {
    return {
      issue: `The selected ${evaluationDays}-day backtest requires held-out evaluation_actuals for every day from ${dateKey(new Date(origin.getTime() + 24 * 60 * 60 * 1000))} through ${dateKey(end)}. Choose a shorter window or upload actuals covering the full window.`,
      actuals: [],
      origin: dateKey(origin),
    };
  }

  return { issue: null, actuals, origin: dateKey(origin) };
}
