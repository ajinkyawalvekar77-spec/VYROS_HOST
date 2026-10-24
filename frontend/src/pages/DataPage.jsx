import { AlertTriangle, Check, FileJson2, FolderOpen, RefreshCw, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { api } from "../services/api";
import { useApp } from "../context/AppContext";
import { DataTable, Button, Card, EmptyState, ErrorNotice, MetricCard, PageHeader, StatusBadge } from "../components/UI";
import { number } from "../utils/format";

const DATA_KEYS = [
  "as_of",
  "synthetic",
  "seed",
  "demand_history",
  "inventory_batches",
  "lanes",
  "transport_costs",
  "capacities",
  "sku_min_shelf_life_days",
  "warehouse_receipts",
];

function payloadForValidation(data) {
  return Object.fromEntries(DATA_KEYS.filter((key) => key in data).map((key) => [key, data[key]]));
}

export default function DataPage() {
  const { demoData, setDemoData, notify } = useApp();
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const fileRef = useRef(null);

  async function validate(data = demoData) {
    if (!data) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.validateData(payloadForValidation(data));
      setReport(result);
      notify(result.valid ? "Dataset validation completed without blocking errors." : "Validation completed with blocking findings.", result.valid ? "success" : "error");
    } catch (caught) {
      setError(caught);
      notify(caught.message, "error");
    } finally {
      setLoading(false);
    }
  }

  async function loadDemo() {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getDemoData({ seed: 71, profile: "compact" });
      setDemoData(result);
      await validate(result);
    } catch (caught) {
      setError(caught);
      setLoading(false);
    }
  }

  async function openJson(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      setError(new Error("JSON dataset files are limited to 10 MiB in the frontend."));
      return;
    }
    if (!file.name.toLowerCase().endsWith(".json")) {
      setError(new Error("This backend accepts JSON records, not CSV uploads."));
      return;
    }
    try {
      const parsed = JSON.parse(await file.text());
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("The JSON root must be an object containing the dataset tables.");
      }
      const data = payloadForValidation(parsed);
      if (!Array.isArray(data.demand_history)) {
        throw new Error("Required dataset table 'demand_history' is missing or invalid.");
      }
      setDemoData({ ...parsed, synthetic: Boolean(parsed.synthetic) });
      setReport(null);
      await validate({ ...parsed, synthetic: Boolean(parsed.synthetic) });
    } catch (caught) {
      setError(caught instanceof SyntaxError ? new Error("The selected file contains invalid JSON.") : caught);
    }
  }

  const findings = report?.findings || [];
  const columns = [
    { key: "severity", label: "Severity", render: (value) => <StatusBadge status={value} /> },
    { key: "table", label: "Table" },
    { key: "row", label: "Row", render: (value) => value == null ? "—" : value + 1 },
    { key: "field", label: "Field" },
    { key: "rule", label: "Rule" },
    { key: "message", label: "Finding" },
  ];

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Data quality" title="Data validation" description="Inspect structure and business constraints before forecasting or allocation." actions={<>
        <input ref={fileRef} className="visually-hidden" type="file" accept=".json,application/json" onChange={openJson} />
        <Button variant="outline" icon={Upload} onClick={() => fileRef.current?.click()}>Import JSON</Button>
        <Button icon={FolderOpen} onClick={loadDemo} disabled={loading}>{loading ? "Loading…" : "Load demo data"}</Button>
      </>} />
      <div className="notice notice-info"><FileJson2 size={17} /><span>Accepted upload: JSON object with engine table arrays. CSV upload is not implemented by the backend. File size is limited to 10 MiB in this interface.</span></div>
      <ErrorNotice error={error} onRetry={() => validate()} />
      {demoData && <div className="transparency-strip"><span className="transparency-dot" /><strong>{demoData.synthetic ? "SYNTHETIC DATA" : "USER-SUPPLIED DATA"}</strong><span>{demoData.synthetic ? `Seed ${demoData.seed ?? "not provided"} · ${demoData.profile || "uploaded"} profile` : "Data provenance is supplied by the user and cannot be verified by the backend."}</span></div>}

      {demoData && <div className="metric-grid metric-grid-three">
        <MetricCard label="Demand rows" value={number(demoData.demand_history?.length, 0)} detail="SKU × destination × date records" icon={FileJson2} tone="blue" />
        <MetricCard label="Inventory batches" value={number(demoData.inventory_batches?.length, 0)} detail={`${number(demoData.warehouse_receipts?.length, 0)} scheduled receipt rows`} icon={FolderOpen} tone="teal" />
        <MetricCard label="Eligible lane rows" value={number(demoData.lanes?.length, 0)} detail={`${number(demoData.capacities?.length, 0)} capacity records`} icon={Check} tone="violet" />
      </div>}

      {report && <Card title="Validation result" subtitle="Report returned by the FastAPI data validation route" action={<StatusBadge status={report.valid ? "valid" : "invalid"} />}>
        <div className="validation-summary">
          <div className={`validation-state ${report.valid ? "validation-ok" : "validation-fail"}`}>{report.valid ? <Check size={18} /> : <AlertTriangle size={18} />}<span><strong>{report.valid ? "No blocking errors" : "Blocking findings detected"}</strong><small>Warnings do not invalidate the report.</small></span></div>
          <div className="validation-count"><strong>{report.error_count}</strong><span>Errors</span></div>
          <div className="validation-count"><strong>{report.warning_count}</strong><span>Warnings</span></div>
        </div>
        <div className="table-scroll"><table className="data-table compact-table"><thead><tr><th>Table</th><th>Rows</th><th>Result</th></tr></thead><tbody>{Object.entries(report.tables || {}).map(([name, table]) => <tr key={name}><td>{name}</td><td>{number(table.row_count, 0)}</td><td><StatusBadge status={table.valid ? "valid" : "invalid"} /></td></tr>)}</tbody></table></div>
      </Card>}

      <Card title="Row-level findings" subtitle={`${findings.length} finding${findings.length === 1 ? "" : "s"} from the backend quality report`}>
        {findings.length ? <DataTable columns={columns} rows={findings} rowKey={(row) => `${row.table}-${row.row}-${row.rule}-${row.field}`} /> : <EmptyState title={report ? "No findings returned" : "No validation report"} description={report ? "The backend reported no errors or warnings for this dataset." : "Load demo data or import a JSON dataset, then run validation."} action={demoData && !report && <Button variant="outline" icon={RefreshCw} onClick={() => validate()} disabled={loading}>Validate dataset</Button>} />}
      </Card>
    </div>
  );
}
