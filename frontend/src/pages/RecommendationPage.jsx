import { ArrowRight, ClipboardCheck, Download, ExternalLink, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Button, Card, DataTable, ErrorNotice, LoadingState, PageHeader, StatusBadge } from "../components/UI";
import { api } from "../services/api";
import { dateTime, number } from "../utils/format";

export default function RecommendationPage() {
  const { runId } = useParams();
  const [record, setRecord] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api.getRun(runId, { signal: controller.signal })
      .then((result) => {
        if (result.operation !== "plan") throw new Error("This run is not a distribution plan.");
        setRecord(result);
      })
      .catch((caught) => { if (caught.code !== "aborted") setError(caught); })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [runId]);

  const result = record?.result || {};
  const verified = result.verification?.is_valid === true;
  const columns = [
    { key: "batch_id", label: "Batch" },
    { key: "sku_id", label: "SKU" },
    { key: "warehouse_id", label: "Source" },
    { key: "destination_id", label: "Destination" },
    { key: "allocated_quantity", label: "Units", render: (value) => number(value, 2) },
    { key: "expiry_date", label: "Expiry" },
  ];

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Decision evidence" title="Recommendation detail" description="Inspect the persisted allocation, engine explanation, and independent validation." actions={record && <Link to={`/app/runs/${encodeURIComponent(runId)}`} className="button button-outline">Run record <ExternalLink size={15} /></Link>} />
      <Link to="/app/plan" className="back-link"><ArrowRight className="back-arrow" size={15} /> Distribution plan</Link>
      <ErrorNotice error={error} />
      {loading ? <LoadingState label="Loading recommendation and evidence…" /> : record && <>
        <div className={`recommendation-callout ${verified ? "callout-verified" : "callout-unverified"}`}>
          {verified ? <ClipboardCheck size={20} /> : <ShieldAlert size={20} />}
          <div><span className="eyebrow">{verified ? "INDEPENDENT CHECKER PASSED" : "NOT VERIFIED AS FEASIBLE"}</span><strong>{verified ? "Engine plan verified" : `Solver status: ${result.solver?.status || record.status}`}</strong><p>{result.verification?.summary || "No independent checker summary was returned."}</p></div>
          <StatusBadge status={verified ? "verified" : "unverified"} />
        </div>
        <div className="detail-grid detail-grid-compact">
          <div><span>Run ID</span><strong className="mono">{record.run_id}</strong></div>
          <div><span>Created</span><strong>{dateTime(record.created_at)}</strong></div>
          <div><span>Solver</span><strong>{result.solver?.status || "Unavailable"}</strong></div>
          <div><span>Forecast model</span><strong>{result.forecast?.model_name || "Unavailable"}{result.forecast?.fallback_used ? " · fallback" : ""}</strong></div>
        </div>
        <Card title="Proposed allocation" subtitle={`${result.plan?.length || 0} lines · quantities and costs reflect actual backend output`}>
          <DataTable columns={columns} rows={result.plan || []} rowKey={(row, index) => `${row.batch_id}-${row.destination_id}-${index}`} empty="No allocation line was returned by the engine." />
        </Card>
        <div className="content-grid">
          <Card title="Why this recommendation" subtitle="Explanation evidence supplied by the engine">
            <p className="body-note">{result.objective_note || "No objective note returned."}</p>
            {result.explanations?.length ? <DataTable columns={Object.keys(result.explanations[0]).slice(0, 7).map((key) => ({ key, label: key.replaceAll("_", " ") }))} rows={result.explanations.slice(0, 100)} /> : <p className="body-note">No explanation records were returned.</p>}
          </Card>
          <Card title="Constraints & trade-offs" subtitle="Checker and solver evidence">
            <div className="verification-summary"><StatusBadge status={verified ? "verified" : "unverified"} /><span>{result.verification?.checks_passed ?? 0} passed</span><span>{result.verification?.checks_failed ?? 0} failed</span></div>
            {result.verification?.checks_not_run?.length ? <div><h3 className="subsection-title">Checks not run</h3><ul className="limitation-list">{result.verification.checks_not_run.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}
            {result.verification?.violations?.length ? <DataTable columns={[{ key: "check", label: "Check" }, { key: "message", label: "Finding" }]} rows={result.verification.violations} /> : <p className="body-note">No checker violations were reported.</p>}
            <div className="detail-row"><span>Objective value</span><strong>{result.solver?.objective_value == null ? "Unavailable" : number(result.solver.objective_value, 3)}</strong></div>
            <div className="detail-row"><span>Constraints added</span><strong>{number(result.solver?.constraints_added, 0)}</strong></div>
          </Card>
        </div>
        {result.forecast?.forecasts?.length > 0 && <Card title="Supporting forecast" subtitle={`${result.forecast.forecasts.length} forecast rows returned for this plan`}><DataTable columns={["sku_id", "destination_id", "forecast_date", "point_forecast", "lower_bound", "upper_bound"].map((key) => ({ key, label: key.replaceAll("_", " "), render: key.endsWith("_forecast") || key.endsWith("_bound") ? (value) => number(value, 2) : undefined }))} rows={result.forecast.forecasts.slice(0, 100)} /></Card>}
      </>}
    </div>
  );
}
