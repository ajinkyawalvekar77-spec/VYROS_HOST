import { AlertCircle, ArrowDownWideNarrow, Search, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../services/api";
import { useApp } from "../context/AppContext";
import { number } from "../utils/format";
import { Button, Card, DataTable, EmptyState, ErrorNotice, LoadingState, PageHeader, SearchInput, StatusBadge } from "../components/UI";

const RISK_DATASET_FIELDS = [
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

function riskPayload(dataset) {
  return Object.fromEntries(
    RISK_DATASET_FIELDS
      .filter((field) => field in dataset)
      .map((field) => [field, dataset[field]]),
  );
}

export default function RiskPage() {
  const { demoData, runs, backtest, notify } = useApp();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState("shortage");
  const [selected, setSelected] = useState(null);
  const latestBacktest = backtest?.run_id || runs.find((run) => run.operation === "backtest")?.run_id;

  async function load(runId = null) {
    setLoading(true);
    setError(null);
    try {
      const result = demoData
        ? await api.riskForDataset(riskPayload(demoData))
        : await api.risk(runId ? { runId } : { seed: 42 });
      setData(result);
    } catch (caught) {
      setError(caught);
      notify(caught.message, "error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setData(null);
    const request = demoData
      ? api.riskForDataset(riskPayload(demoData), { signal: controller.signal })
      : latestBacktest
        ? api.risk({ runId: latestBacktest, signal: controller.signal })
        : api.risk({ seed: 42, signal: controller.signal });
    request
      .then(setData).catch((caught) => { if (caught.code !== "aborted") setError(caught); }).finally(() => setLoading(false));
    return () => controller.abort();
  }, [latestBacktest, demoData]);

  const indicators = data?.indicators || [];
  const filtered = useMemo(() => {
    let rows = indicators.filter((item) => {
      const text = `${item.sku_id || ""} ${item.destination_id || ""} ${item.name || ""} ${item.indicator || ""} ${item.policy || ""}`.toLowerCase();
      const flagged = item.is_flagged ?? (Number(item.value) > 0);
      return text.includes(query.toLowerCase()) &&
        (filter === "all" || (filter === "flagged" ? flagged : !flagged));
    });
    rows = [...rows].sort((a, b) => {
      const left = sort === "shortage" ? Number(a.supply_shortage_units ?? a.value ?? 0) : String(a.sku_id || a.policy || a.name || "");
      const right = sort === "shortage" ? Number(b.supply_shortage_units ?? b.value ?? 0) : String(b.sku_id || b.policy || b.name || "");
      return sort === "shortage" ? right - left : left.localeCompare(right);
    });
    return rows;
  }, [indicators, query, filter, sort]);

  const columns = [
    { key: "indicator", label: "Indicator", render: (value, row) => row.name || value || "Measured run metric" },
    { key: "sku_id", label: "SKU / policy", render: (value, row) => value || row.policy || "Network" },
    { key: "flag", label: "Signal", render: (_value, row) => <StatusBadge status={(row.is_flagged ?? Number(row.value) > 0) ? "flagged" : "measured"} /> },
    { key: "supply_shortage_units", label: "Shortage / value", render: (value, row) => value != null ? `${number(value)} units` : row.value != null ? number(row.value) : "Unavailable" },
    { key: "forecast_horizon_demand_units", label: "Forecast demand", render: (value, row) => value != null ? `${number(value)} units` : row.point_demand_units != null ? `${number(row.point_demand_units)} units` : "—" },
    { key: "network_days_of_cover", label: "Days of cover", render: (value) => value == null ? "Unavailable" : number(value) },
    { key: "details", label: "", render: (_value, row) => <button className="text-button" onClick={() => setSelected(row)}>Details</button> },
  ];

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Exceptions & exposure" title="Risk overview" description="Measured indicators from the active dataset or a completed run. No composite risk score is generated." actions={<Button variant="outline" icon={ShieldCheck} onClick={() => load(latestBacktest || null)} disabled={loading}>Refresh indicators</Button>} />
      <div className="transparency-strip"><span className="transparency-dot" /><strong>{data?.dataset_id ? data.synthetic ? "SYNTHETIC DATASET INDICATORS" : "UPLOADED DATASET INDICATORS" : data?.run_id ? data.synthetic ? "SYNTHETIC RUN MEASURES" : "RUN-LINKED MEASURES" : data?.synthetic ? "SYNTHETIC DEMO INDICATORS" : "MEASURED API INDICATORS"}</strong><span>{data?.dataset_id ? `Dataset ${data.dataset_id.slice(0, 12)} · ${data.indicator_scope}` : data?.run_id ? `Source run ${data.run_id} · ${data.indicator_scope || ""}` : data?.indicator_scope || "Measured API indicators"}</span></div>
      {data?.risk_score == null && <div className="notice notice-info"><ShieldCheck size={17} /><span>No weighted risk score or inferred severity is shown. Indicators are reported in their source units; unsupported exposure measures are listed below.</span></div>}
      <ErrorNotice error={error} onRetry={() => load(latestBacktest || null)} />
      {loading && !data ? <LoadingState label="Loading risk indicators from the backend…" /> : <>
        <div className="filter-toolbar">
          <SearchInput value={query} onChange={setQuery} placeholder="Search SKU or indicator" />
          <label className="select-control">Signal
            <select value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">All indicators</option><option value="flagged">Flagged</option><option value="clear">Not flagged</option></select>
          </label>
          <label className="select-control">Sort
            <select value={sort} onChange={(event) => setSort(event.target.value)}><option value="shortage">Largest measured value</option><option value="sku">SKU / name</option></select>
          </label>
        </div>
        <Card title="Risk indicators" subtitle={`${filtered.length} of ${indicators.length} backend-reported measures`} action={<span className="subtle-action"><ArrowDownWideNarrow size={15} /> Sorted by measured value</span>}>
          <DataTable columns={columns} rows={filtered} rowKey={(row, index) => `${row.policy || ""}-${row.sku_id || row.name || row.indicator}-${index}`} empty="No indicators match these filters." />
        </Card>
        {data?.unavailable_indicators?.length > 0 && <Card title="Unavailable measures" subtitle="The backend identifies these as unsupported by the current data contract"><ul className="limitation-list">{data.unavailable_indicators.map((item) => <li key={item}><AlertCircle size={15} />{item}</li>)}</ul></Card>}
        {data?.limitations?.length > 0 && <Card title="Interpretation notes"><ul className="limitation-list">{data.limitations.map((item) => <li key={item}>{item}</li>)}</ul></Card>}
      </>}
      {selected && <div className="drawer-backdrop" role="presentation" onClick={() => setSelected(null)}><aside className="detail-drawer" role="dialog" aria-modal="true" aria-label="Risk indicator details" onClick={(event) => event.stopPropagation()}><button className="drawer-close" onClick={() => setSelected(null)} aria-label="Close detail">×</button><span className="eyebrow">MEASURED INDICATOR</span><h2>{selected.name || selected.indicator || "Risk measure"}</h2><p className="detail-lede">Values below are returned by the backend; no additional threshold or score is inferred in this view.</p><dl className="detail-list">{Object.entries(selected).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{typeof value === "object" ? JSON.stringify(value) : value == null ? "Unavailable" : String(value)}</dd></div>)}</dl></aside></div>}
    </div>
  );
}
