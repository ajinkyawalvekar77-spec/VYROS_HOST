import { Activity, AlertTriangle, Download, Play, ShieldCheck, Timer } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../services/api";
import { useApp } from "../context/AppContext";
import { number, percent } from "../utils/format";
import { Button, Card, DataTable, EmptyState, ErrorNotice, MetricCard, PageHeader, StatusBadge } from "../components/UI";
import { backtestInput } from "../utils/workflowInputs";

export default function BacktestPage() {
  const { demoData, setDemoData, backtest, setBacktest, rememberRun, notify } = useApp();
  const [days, setDays] = useState(56);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const inputStatus = demoData ? backtestInput(demoData, days) : null;

  async function run() {
    setLoading(true);
    setError(null);
    try {
      const data = demoData || await api.getDemoData({ seed: 71, profile: "compact" });
      if (!demoData) setDemoData(data);
      const evaluation = backtestInput(data, days);
      if (evaluation.issue) {
        setError(new Error(evaluation.issue));
        return;
      }
      const result = await api.backtest({
        as_of: evaluation.origin,
        synthetic: Boolean(data.synthetic),
        seed: data.seed,
        demand_history: data.demand_history,
        inventory_batches: data.inventory_batches,
        warehouse_receipts: data.warehouse_receipts || [],
        lanes: data.lanes,
        transport_costs: data.transport_costs,
        capacities: data.capacities,
        sku_min_shelf_life_days: data.sku_min_shelf_life_days,
        evaluation_actuals: evaluation.actuals,
        evaluation_days: days,
        solver_time_limit_seconds: 60,
      });
      setBacktest(result);
      rememberRun({ ...result, operation: "backtest" });
      notify(`Backtest ${result.status} · ${result.policy_metrics.length} policy results returned.`, result.status === "succeeded" ? "success" : "error");
    } catch (caught) {
      setError(caught);
      if (caught.runId) rememberRun({ run_id: caught.runId, operation: "backtest", status: "failed" });
      notify(caught.message, "error");
    } finally {
      setLoading(false);
    }
  }

  async function exportRun(format) {
    if (!backtest?.run_id) return;
    try {
      const { blob, filename } = await api.exportRun(backtest.run_id, format);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (caught) {
      setError(caught);
    }
  }

  const metrics = backtest?.policy_metrics || [];
  const chartRows = metrics.map((row) => ({
    policy: row.policy,
    fillRate: Number.isFinite(row.fill_rate) ? row.fill_rate * 100 : null,
    freightCost: row.freight_cost,
    expiredUnits: row.expired_units,
  }));
  const columns = [
    { key: "policy", label: "Policy" },
    { key: "demand_units", label: "Demand (units)", render: (value) => number(value, 0) },
    { key: "fill_rate", label: "Fill rate", render: (value) => percent(value) },
    { key: "unmet_demand_rate", label: "Unmet rate", render: (value) => percent(value) },
    { key: "stockout_day_rate", label: "Stockout-day rate", render: (value) => percent(value) },
    { key: "expired_units", label: "Expired units", render: (value) => number(value, 0) },
    { key: "freight_cost", label: "Freight cost", render: (value) => number(value, 2) },
    { key: "modeled_total_cost", label: "Modeled cost", render: (value) => number(value, 2) },
    { key: "constraint_violations", label: "Violations", render: (value) => <StatusBadge status={value === 0 ? "valid" : "invalid"}>{number(value, 0)}</StatusBadge> },
  ];

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Policy evaluation" title="Backtesting" description="Chronological daily replay using the backend’s forecasting, allocation, benchmark, and simulation workflows." actions={<>
        <label className="select-control horizon-select">Evaluation window<select value={days} onChange={(event) => setDays(Number(event.target.value))}><option value={56}>56 days · 8 weekly cycles</option><option value={28}>28 days · 4 weekly cycles</option><option value={14}>14 days · 2 weekly cycles</option><option value={7}>7 days · 1 weekly cycle</option></select></label>
        <Button icon={Play} onClick={run} disabled={loading || Boolean(inputStatus?.issue)}>{loading ? "Running evaluation…" : "Run backtest"}</Button>
      </>} />
      <div className="notice notice-info"><Activity size={17} /><span>The engine supports Optiqo, cheapest-first, and FEFO-first policies. These are not the PRD’s specifically defined B1/B2 methods. Results use the selected dataset and are simulation measurements—not verified real-world savings.</span></div>
      {demoData && <div className="transparency-strip"><span className="transparency-dot" /><strong>{demoData.synthetic ? "SYNTHETIC EVALUATION" : "USER-SUPPLIED EVALUATION"}</strong><span>Seed {demoData.seed ?? "not provided"} · 7-day rolling forecast horizon · {days} held-out days</span></div>}
      {inputStatus?.issue && <div className="notice notice-warning"><Activity size={18} /><span>{inputStatus.issue} <Link to="/app/data">Open Data Validation to download a complete demo JSON or upload a full dataset.</Link></span></div>}
      <ErrorNotice error={inputStatus?.issue ? null : error} onRetry={run} />

      {backtest && <>
        <div className="plan-result-banner">
          <div className="plan-status-icon"><ShieldCheck size={19} /></div>
          <div className="plan-status-copy"><span className="eyebrow">BACKTEST RUN · {backtest.run_id}</span><strong>{backtest.synthetic ? "Synthetic simulation results" : "Evaluation results"}</strong><span>{backtest.evaluation_start} through {backtest.evaluation_end} · {backtest.evaluation_days} daily periods</span></div>
          <StatusBadge status={backtest.status} />
        </div>
        <div className="metric-grid metric-grid-three">
          <MetricCard label="Policies evaluated" value={number(metrics.length, 0)} detail={backtest.policies?.join(" · ") || "Unavailable"} icon={Activity} tone="blue" />
          <MetricCard label="Evaluation window" value={`${backtest.evaluation_days} days`} detail={`${backtest.cycles?.length || 0} policy-cycle records`} icon={Timer} tone="violet" />
          <MetricCard label="Recorded plan lines" value={number(backtest.allocations?.length, 0)} detail={`${number(backtest.daily_inventory?.length, 0)} batch balance rows`} icon={ShieldCheck} tone="teal" />
        </div>
        <div className="content-grid">
          <Card title="Forecast quality" subtitle="Chronological forecast metrics, per policy">
            {Object.keys(backtest.forecast_metrics || {}).length ? <DataTable columns={[
              { key: "policy", label: "Policy" },
              { key: "observation_count", label: "Matched observations", render: (value) => number(value, 0) },
              { key: "mae_units", label: "MAE (units)", render: (value) => number(value, 2) },
              { key: "rmse_units", label: "RMSE (units)", render: (value) => number(value, 2) },
              { key: "wape", label: "Daily WAPE", render: (value) => percent(value) },
              { key: "weekly_wape", label: "Weekly WAPE", render: (value) => percent(value) },
              { key: "bias", label: "Bias", render: (value) => percent(value) },
              { key: "interval_coverage", label: "Interval coverage", render: (value) => percent(value) },
            ]} rows={Object.entries(backtest.forecast_metrics).map(([policy, values]) => ({ policy, ...values }))} /> : <EmptyState title="No forecast metrics returned" description="Forecast metric outputs are unavailable for this run." />}
          </Card>
          <Card title="Policy comparison" subtitle="Measured values from this backtest run">
            {chartRows.length ? <div className="chart-wrap chart-medium"><ResponsiveContainer width="100%" height="100%"><BarChart data={chartRows} margin={{ top: 10, right: 10, left: 0, bottom: 4 }}><CartesianGrid strokeDasharray="3 5" vertical={false} /><XAxis dataKey="policy" tickLine={false} axisLine={false} /><YAxis yAxisId="left" tickFormatter={(value) => `${value}%`} tickLine={false} axisLine={false} /><Tooltip /><Legend /><Bar yAxisId="left" dataKey="fillRate" name="Fill rate (%)" fill="#5577ed" radius={[5, 5, 0, 0]} /></BarChart></ResponsiveContainer></div> : <EmptyState title="No policy results" />}
          </Card>
        </div>
        <Card title="Service, inventory & freight" subtitle="All metrics are computed from replayed policy events">
          <DataTable columns={columns} rows={metrics} rowKey={(row) => row.policy} />
        </Card>
        <Card title="Evaluation assumptions & limitations" subtitle="Returned with the run; see also the method-level notes">
          <ul className="limitation-list">{(backtest.assumptions || []).map((item) => <li key={item}>{item}</li>)}</ul>
          <div className="card-bottom-actions"><Button variant="outline" icon={Download} onClick={() => exportRun("csv")}>Export results CSV</Button><Button variant="quiet" onClick={() => exportRun("json")}>Export full JSON</Button></div>
        </Card>
        {backtest.cycles?.some((cycle) => cycle.status === "failed" || cycle.verification?.is_valid === false) && <div className="notice notice-warning"><AlertTriangle size={17} /><span>One or more policy cycles failed or were not verified. Inspect the cycle records before interpreting the aggregate.</span></div>}
      </>}
      {!backtest && <Card><EmptyState title="No backtest run recorded" description="Run an evaluation to compare the engine’s supported policies against the same synthetic held-out demand and constraints." action={<Button icon={Play} onClick={run} disabled={loading}>{loading ? "Running…" : "Run 56-day backtest"}</Button>} /></Card>}
    </div>
  );
}
