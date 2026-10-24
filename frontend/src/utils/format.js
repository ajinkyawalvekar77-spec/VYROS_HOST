export const number = (value, digits = 1) =>
  Number.isFinite(Number(value))
    ? new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(Number(value))
    : "Unavailable";

export const percent = (value, digits = 1) =>
  Number.isFinite(Number(value))
    ? `${new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(Number(value) * 100)}%`
    : "Unavailable";

export const dateTime = (value) => {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value)
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
};

export const dateOnly = (value) => {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value)
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" }).format(date);
};

export const total = (rows, key) =>
  Array.isArray(rows)
    ? rows.reduce((sum, row) => sum + (Number.isFinite(Number(row?.[key])) ? Number(row[key]) : 0), 0)
    : 0;

export const shortId = (value) => (value ? `${value.slice(0, 8)}…` : "—");
