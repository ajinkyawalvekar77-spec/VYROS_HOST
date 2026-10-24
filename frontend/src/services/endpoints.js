export const endpoints = {
  health: "/api/health",
  demoData: "/api/demo-data",
  validate: "/api/data/validate",
  forecast: "/api/forecast",
  plan: "/api/plan",
  risk: "/api/risk",
  backtest: "/api/backtest",
  run: (runId) => `/api/runs/${encodeURIComponent(runId)}`,
  exportRun: (runId, format = "json") =>
    `/api/runs/${encodeURIComponent(runId)}/export?format=${encodeURIComponent(format)}`,
};
