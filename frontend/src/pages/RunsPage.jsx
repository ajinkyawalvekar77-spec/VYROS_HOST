import { Clock3, ExternalLink, Search, SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Button, Card, DataTable, EmptyState, PageHeader, SearchInput, StatusBadge } from "../components/UI";
import { useApp } from "../context/AppContext";
import { dateTime, shortId } from "../utils/format";

export default function RunsPage() {
  const { runs, notify } = useApp();
  const [query, setQuery] = useState("");
  const [operation, setOperation] = useState("all");
  const filtered = useMemo(() => runs.filter((run) => {
    const text = `${run.run_id} ${run.operation} ${run.status}`.toLowerCase();
    return text.includes(query.toLowerCase()) && (operation === "all" || run.operation === operation);
  }), [runs, query, operation]);
  const columns = [
    { key: "run_id", label: "Run reference", render: (value) => <span className="mono">{shortId(value)}</span> },
    { key: "operation", label: "Operation", render: (value) => <span className="capitalize">{value}</span> },
    { key: "status", label: "Status", render: (value) => <StatusBadge status={value} /> },
    { key: "created_at", label: "Created", render: dateTime },
    { key: "open", label: "", render: (_value, row) => <Link className="table-link" to={`/app/runs/${encodeURIComponent(row.run_id)}`}>Open <ExternalLink size={13} /></Link> },
  ];

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Execution records" title="Run history" description="Inspect runs initiated from this browser. The API does not provide a list-all-runs route." actions={<Button variant="outline" icon={Clock3} onClick={() => notify("Only run IDs returned to this browser can be listed; the backend has no list endpoint.", "info")}>About run history</Button>} />
      <div className="notice notice-info"><Search size={16} /><span>Run references are stored locally in this browser after real API responses. Use a known backend run ID to open any persisted record.</span></div>
      <div className="filter-toolbar"><SearchInput value={query} onChange={setQuery} placeholder="Search run ID, operation, or status" /><label className="select-control"><SlidersHorizontal size={14} /> Type<select value={operation} onChange={(event) => setOperation(event.target.value)}><option value="all">All run types</option><option value="forecast">Forecast</option><option value="plan">Plan</option><option value="backtest">Backtest</option></select></label></div>
      <Card title="Recent execution runs" subtitle={`${filtered.length} browser-known record${filtered.length === 1 ? "" : "s"}`}>
        {filtered.length ? <DataTable columns={columns} rows={filtered} rowKey={(run) => run.run_id} /> : <EmptyState title="No matching runs" description={runs.length ? "Try a different search or operation filter." : "No backend runs have been initiated from this browser yet."} />}
      </Card>
      <Card className="run-id-lookup">
        <div><span className="eyebrow">LOOK UP A PERSISTED RUN</span><p>Run IDs are UUIDs returned by forecast, plan, and backtest operations.</p></div>
        <RunLookup />
      </Card>
    </div>
  );
}

function RunLookup() {
  const [value, setValue] = useState("");
  return <form className="lookup-form" onSubmit={(event) => { event.preventDefault(); if (value.trim()) window.location.assign(`/app/runs/${encodeURIComponent(value.trim())}`); }}>
    <input aria-label="Run ID" value={value} onChange={(event) => setValue(event.target.value)} placeholder="Paste a run ID" />
    <Button type="submit" disabled={!value.trim()}>Open run</Button>
  </form>;
}
