import { ArrowRight, Download, PackageCheck, RefreshCw, ShieldCheck, Truck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../services/api";
import { useApp } from "../context/AppContext";
import { dateTime, number, total } from "../utils/format";
import { Button, Card, DataTable, EmptyState, ErrorNotice, MetricCard, PageHeader, StatusBadge } from "../components/UI";

export default function PlanPage() {
  const { demoData, setDemoData, plan, setPlan, rememberRun, notify } = useApp();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [horizon, setHorizon] = useState(7);
  const [exporting, setExporting] = useState(false);

  async function generate() {
    setLoading(true);
    setError(null);
    try {
      const data = demoData || await api.getDemoData({ seed: 71, profile: "compact" });
      if (!demoData) setDemoData(data);
      const result = await api.plan({
        as_of: data.as_of,
        synthetic: Boolean(data.synthetic),
        seed: data.seed,
        demand_history: data.demand_history,
        inventory_batches: data.inventory_batches,
        lanes: data.lanes,
        transport_costs: data.transport_costs,
        capacities: data.capacities,
        sku_min_shelf_life_days: data.sku_min_shelf_life_days,
        held_out_actuals: data.held_out_actuals,
        horizon_days: horizon,
      });
      setPlan(result);
      rememberRun({
        run_id: result.run_id,
        operation: "plan",
        created_at: result.created_at,
        status: result.verification?.is_valid ? "succeeded" : "partial_failure",
      });
      notify(result.verification?.is_valid ? "Plan completed and independently verified." : "Plan returned without a valid independent verification.", result.verification?.is_valid ? "success" : "error");
    } catch (caught) {
      setError(caught);
      if (caught.runId) rememberRun({ run_id: caught.runId, operation: "plan", status: "failed" });
      notify(caught.message, "error");
    } finally {
      setLoading(false);
    }
  }

  async function exportResult(format = "csv") {
    if (!plan?.run_id) {
      notify("This plan has no persisted backend run ID to export.", "error");
      return;
    }
    setExporting(true);
    try {
      const { blob, filename } = await api.exportRun(plan.run_id, format);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (caught) {
      setError(caught);
    } finally {
      setExporting(false);
    }
  }

  const planRows = plan?.plan || [];
  const freight = plan?.benchmark?.metrics?.find((row) => row.policy === "optiqo")?.freight_cost;
  const columns = [
    { key: "sku_id", label: "SKU" },
    { key: "warehouse_id", label: "Source warehouse" },
    { key: "destination_id", label: "Destination" },
    { key: "batch_id", label: "Batch" },
    { key: "allocated_quantity", label: "Allocated units", render: (value) => number(value, 2) },
    { key: "expiry_date", label: "Expiry" },
    { key: "unit_transport_cost", label: "Unit freight", render: (value) => value == null ? "Unavailable" : number(value, 2) },
  ];

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Allocation workspace" title="Distribution plan" description="Generate an engine-backed allocation and inspect its solver status, independent checks, and supporting evidence." actions={<>
        <label className="select-control horizon-select">Planning horizon<select value={horizon} onChange={(event) => setHorizon(Number(event.target.value))}><option value={7}>7 days</option><option value={14}>14 days</option><option value={28}>28 days</option></select></label>
        <Button icon={loading ? RefreshCw : Truck} onClick={generate} disabled={loading}>{loading ? "Planning…" : "Generate plan"}</Button>
      </>} />
      {demoData && <div className="transparency-strip"><span className="transparency-dot" /><strong>{demoData.synthetic ? "SYNTHETIC INPUT" : "USER INPUT"}</strong><span>{demoData.synthetic ? `Seed ${demoData.seed} · backend demo data` : "User-supplied data; provenance is not independently verified."}</span></div>}
      {!demoData && <Card className="inline-empty"><PackageCheck size={20} /><div><strong>No planning dataset loaded</strong><p>Generate a plan to load the backend’s compact synthetic dataset or validate uploaded data first.</p></div></Card>}
      <ErrorNotice error={error} onRetry={generate} />
      {plan && <>
        <div className="plan-result-banner">
          <div className="plan-status-icon"><ShieldCheck size={19} /></div>
          <div className="plan-status-copy"><span className="eyebrow">ENGINE RESULT · {plan.run_id || "RUN ID UNAVAILABLE"}</span><strong>{plan.verification?.is_valid ? "Independently verified allocation" : "Plan is not verified as feasible"}</strong><span>{plan.verification?.summary || "Verification details returned by the backend."}</span></div>
          <div className="plan-status-badges"><StatusBadge status={plan.solver?.status} /><StatusBadge status={plan.verification?.is_valid ? "verified" : "unverified"} /></div>
        </div>
        <div className="metric-grid">
          <MetricCard label="Allocated lines" value={number(planRows.length, 0)} detail="Actual engine plan rows" icon={PackageCheck} tone="blue" />
          <MetricCard label="Allocated units" value={`${number(total(planRows, "allocated_quantity"), 2)} units`} detail="Continuous quantities per engine contract" icon={Truck} tone="teal" />
          <MetricCard label="Freight cost" value={freight == null ? "Unavailable" : number(freight, 2)} detail={freight == null ? "No benchmark cost returned" : "Engine benchmark · cost units"} icon={ArrowRight} tone="violet" />
          <MetricCard label="Checker violations" value={number(plan.verification?.checks_failed, 0)} detail={plan.verification?.checks_not_run?.length ? `${plan.verification.checks_not_run.length} checks not run` : "Checker result from backend"} icon={ShieldCheck} tone={plan.verification?.is_valid ? "green" : "amber"} />
        </div>
        <Card title="Allocation lines" subtitle={`Solver: ${plan.solver?.status || "unknown"} · ${dateTime(plan.created_at)}`} action={plan.run_id && <Link to={`/app/recommendations/${encodeURIComponent(plan.run_id)}`} className="small-link">Recommendation detail <ArrowRight size={14} /></Link>}>
          <DataTable columns={columns} rows={planRows} rowKey={(row, index) => `${row.batch_id}-${row.destination_id}-${index}`} empty="The engine returned no allocation lines." />
          <div className="card-bottom-actions"><Button variant="outline" icon={Download} onClick={() => exportResult("csv")} disabled={exporting || !plan.run_id}>{exporting ? "Preparing export…" : "Export run CSV"}</Button><Button variant="quiet" onClick={() => exportResult("json")} disabled={exporting || !plan.run_id}>Download JSON</Button></div>
        </Card>
        <div className="content-grid">
          <Card title="Independent verification" subtitle="Engine checker output">
            <div className="verification-summary"><StatusBadge status={plan.verification?.is_valid ? "verified" : "unverified"} /><span>{plan.verification?.checks_passed ?? 0} checks passed</span><span>{plan.verification?.checks_failed ?? 0} failed</span></div>
            <p className="body-note">{plan.verification?.summary || "No checker summary was returned."}</p>
            {plan.verification?.checks_not_run?.length > 0 && <ul className="limitation-list">{plan.verification.checks_not_run.map((item) => <li key={item}>{item}</li>)}</ul>}
            {plan.verification?.violations?.length > 0 && <DataTable columns={[{ key: "check", label: "Check" }, { key: "message", label: "Finding" }]} rows={plan.verification.violations} />}
          </Card>
          <Card title="Decision notes" subtitle="Objective and benchmark from the engine">
            <p className="body-note">{plan.objective_note}</p>
            <div className="detail-row"><span>Forecast model</span><strong>{plan.forecast?.model_name || "Unavailable"}</strong></div>
            <div className="detail-row"><span>Fallback used</span><strong>{plan.forecast?.fallback_used ? "Yes" : "No"}</strong></div>
            <div className="detail-row"><span>Recommendation reference</span><strong className="mono">{plan.run_id || "Not recorded"}</strong></div>
          </Card>
        </div>
        {plan.explanations?.length > 0 && <Card title="Engine explanations" subtitle="Evidence returned by the allocation explanation function"><DataTable columns={Object.keys(plan.explanations[0]).slice(0, 6).map((key) => ({ key, label: key.replaceAll("_", " ") }))} rows={plan.explanations.slice(0, 100)} /></Card>}
      </>}
      {!plan && <Card className="inline-empty"><EmptyState title="No allocation result yet" description="The backend will return solver status, proposed shipments, and independent verification. A failed or unchecked plan will not be labelled feasible." action={<Button onClick={generate} icon={Truck} disabled={loading}>{loading ? "Planning…" : "Generate a plan"}</Button>} /></Card>}
    </div>
  );
}
