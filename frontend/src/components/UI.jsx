import { AlertCircle, CheckCircle2, Info, LoaderCircle, Search } from "lucide-react";
import { Link } from "react-router-dom";
import { dateTime, shortId } from "../utils/format";

export function Button({ children, variant = "primary", className = "", icon: Icon, ...props }) {
  return (
    <button className={`button button-${variant} ${className}`} {...props}>
      {Icon && <Icon size={16} strokeWidth={2} />}
      {children}
    </button>
  );
}

export function IconButton({ label, children, className = "", ...props }) {
  return (
    <button className={`icon-button ${className}`} aria-label={label} title={label} {...props}>
      {children}
    </button>
  );
}

export function StatusBadge({ status, children }) {
  const value = String(status || "unknown").toLowerCase().replaceAll(" ", "_");
  return <span className={`status-badge status-${value}`}>{children || status || "Unknown"}</span>;
}

export function MetricCard({ label, value, detail, icon: Icon, tone = "blue" }) {
  return (
    <article className="metric-card">
      <div className={`metric-icon tone-${tone}`}>{Icon && <Icon size={17} />}</div>
      <div className="metric-copy">
        <span className="eyebrow">{label}</span>
        <strong>{value ?? "Unavailable"}</strong>
        {detail && <span className="metric-detail">{detail}</span>}
      </div>
    </article>
  );
}

export function PageHeader({ eyebrow, title, description, actions }) {
  return (
    <div className="page-header">
      <div>
        {eyebrow && <div className="eyebrow page-eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export function Card({ title, subtitle, action, className = "", children }) {
  return (
    <section className={`surface-card ${className}`}>
      {(title || subtitle || action) && (
        <header className="card-header">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <p>{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function EmptyState({ title = "Nothing to show yet", description, action }) {
  return (
    <div className="empty-state">
      <span className="empty-icon"><Info size={20} /></span>
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {action}
    </div>
  );
}

export function ErrorNotice({ error, title = "Request could not be completed", onRetry }) {
  if (!error) return null;
  return (
    <div className="notice notice-error" role="alert">
      <AlertCircle size={18} />
      <div>
        <strong>{title}</strong>
        <p>{error.message || String(error)}</p>
      </div>
      {onRetry && <Button variant="quiet" onClick={onRetry}>Retry</Button>}
    </div>
  );
}

export function SuccessNotice({ children }) {
  return <div className="notice notice-success"><CheckCircle2 size={18} /><span>{children}</span></div>;
}

export function LoadingState({ label = "Loading Optiqo data…" }) {
  return <div className="loading-state"><LoaderCircle className="spin" size={19} /><span>{label}</span></div>;
}

export function SearchInput({ value, onChange, placeholder = "Search…" }) {
  return (
    <label className="search-input">
      <Search size={16} />
      <input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
    </label>
  );
}

export function DataTable({ columns, rows, rowKey, empty = "No matching records." }) {
  if (!rows?.length) return <EmptyState title={empty} />;
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead><tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={rowKey ? rowKey(row) : row.id || `${index}`}>
              {columns.map((column) => (
                <td key={column.key}>{column.render ? column.render(row[column.key], row) : row[column.key] ?? "—"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ApiStatus({ health, loading }) {
  return (
    <div className={`api-status ${health?.status === "running" && health?.engine_ready ? "api-online" : "api-offline"}`}>
      <span className="api-dot" />
      {loading ? "Checking API" : health?.engine_ready ? "Engine connected" : health?.status ? "Engine unavailable" : "API disconnected"}
    </div>
  );
}

export function ToastHost({ toast }) {
  if (!toast) return null;
  return <div className={`toast toast-${toast.type}`} role="status">{toast.type === "error" ? <AlertCircle size={17} /> : <Info size={17} />}{toast.message}</div>;
}

export function RunLink({ run }) {
  return (
    <Link className="run-link" to={`/app/runs/${encodeURIComponent(run.run_id)}`}>
      <span className="mono">{shortId(run.run_id)}</span>
      <span>{run.operation}</span>
      <span>{dateTime(run.created_at)}</span>
    </Link>
  );
}
