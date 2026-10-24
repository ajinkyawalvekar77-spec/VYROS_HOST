import { ArrowLeft, Download, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Button, Card, DataTable, EmptyState, ErrorNotice, LoadingState, PageHeader, StatusBadge } from "../components/UI";
import { useApp } from "../context/AppContext";
import { api } from "../services/api";
import { dateTime, shortId } from "../utils/format";

export default function RunDetailPage() {
  const { runId } = useParams();
  const { rememberRun } = useApp();
  const [record, setRecord] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);

  async function load(signal) {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getRun(runId, { signal });
      setRecord(result);
      rememberRun(result);
    } catch (caught) {
      if (caught.code !== "aborted") setError(caught);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [runId]);

  async function exportRun(format) {
    setExporting(true);
    try {
      const { blob, filename } = await api.exportRun(runId, format);
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

  const result = record?.result;
  const planRows = result?.plan || result?.allocations || [];
  const policyRows = result?.policy_metrics || [];
  const forecastRows = result?.forecasts || result?.forecast?.forecasts || [];
  const dailyRows = result?.daily || [];

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Persisted execution" title="Run details" description={`Backend record ${runId || ""}`} actions={<><Button variant="outline" icon={RefreshCw} onClick={() => load()} disabled={loading}>Refresh</Button><Button icon={Download} onClick={() => exportRun("json")} disabled={exporting || !record}>Export JSON</Button></>} />
      <Link to="/app/runs" className="back-link"><ArrowLeft size={15} /> Run history</Link>
      <ErrorNotice error={error} onRetry={() => load()} />
      {loading && !record ? <LoadingState label="Fetching the persisted backend run…" /> : record && <>
        <div className="run-detail-header"><div><span className="eyebrow">RUN ID</span><strong className="mono">{record.run_id}</strong></div><div><span className="eyebrow">OPERATION</span><strong className="capitalize">{record.operation}</strong></div><div><span className="eyebrow">CREATED</span><strong>{dateTime(record.created_at)}</strong></div><StatusBadge status={record.status} /></div>
        {record.error && <div className="notice notice-error"><strong>{record.error.exception_type || record.error.code}</strong><span>{record.error.message}</span></div>}
        {result && <div className="card-bottom-actions card-bottom-top"><Button variant="outline" icon={Download} onClick={() => exportRun("csv")} disabled={exporting}>Export CSV</Button><Button variant="quiet" onClick={() => exportRun("json")} disabled={exporting}>Export JSON</Button>{record.operation === "plan" && <Link className="small-link" to={`/app/recommendations/${encodeURIComponent(record.run_id)}`}>Open recommendation detail</Link>}</div>}
        <Card title="Run configuration" subtitle="Recorded request provenance and effective settings">
          <div className="detail-grid"><div><span>Input SHA-256</span><strong className="mono">{record.input_provenance?.sha256 || "Unavailable"}</strong></div><div><span>Synthetic</span><strong>{record.input_provenance?.synthetic ? "Yes" : "Not declared"}</strong></div><div><span>Seed</span><strong>{record.input_provenance?.seed ?? "Not declared"}</strong></div><div><span>Configuration</span><pre>{JSON.stringify(record.configuration, null, 2)}</pre></div></div>
        </Card>
        {record.operation === "forecast" && <Card title="Forecast output" subtitle={`${forecastRows.length} actual forecast rows returned`}><DataTable columns={forecastRows[0] ? Object.keys(forecastRows[0]).slice(0, 8).map((key) => ({ key, label: key.replaceAll("_", " ") })) : []} rows={forecastRows.slice(0, 200)} empty="No forecast rows in this record." /></Card>}
        {record.operation === "plan" && <Card title="Allocation and verification" subtitle="Actual engine result"><div className="verification-summary"><StatusBadge status={result.verification?.is_valid ? "verified" : "unverified"} /><span>Solver: {result.solver?.status}</span><span>{result.verification?.checks_failed ?? 0} checker failures</span></div><DataTable columns={planRows[0] ? Object.keys(planRows[0]).slice(0, 8).map((key) => ({ key, label: key.replaceAll("_", " ") })) : []} rows={planRows} empty="No allocation rows." /></Card>}
        {record.operation === "backtest" && <>
          <Card title="Policy comparison" subtitle={`${policyRows.length} actual policy results`}><DataTable columns={policyRows[0] ? Object.keys(policyRows[0]).filter((key) => !["constraint_violation_details"].includes(key)).map((key) => ({ key, label: key.replaceAll("_", " ") })) : []} rows={policyRows} /></Card>
          <Card title="Daily replay rows" subtitle={`${dailyRows.length} SKU × destination × day records`}><DataTable columns={dailyRows[0] ? Object.keys(dailyRows[0]).map((key) => ({ key, label: key.replaceAll("_", " ") })) : []} rows={dailyRows.slice(0, 250)} empty="No daily replay rows." />{dailyRows.length > 250 && <p className="body-note">Showing the first 250 rows. Download the full run export for all records.</p>}</Card>
        </>}
        <Card title="Input row counts"><div className="row-count-list">{Object.entries(record.input_provenance?.row_counts || {}).map(([key, count]) => <div key={key}><span>{key.replaceAll("_", " ")}</span><strong>{count}</strong></div>)}</div></Card>
      </>}
      {!loading && !record && !error && <EmptyState title={`Run ${shortId(runId)} not found`} description="The backend did not return a record for this run ID." />}
    </div>
  );
}
