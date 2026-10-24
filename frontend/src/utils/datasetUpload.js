const DEMAND_COLUMNS = ["sku_id", "destination_id", "demand_date", "quantity"];

function csvRecords(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        field += character;
      }
    } else if (character === '"' && field.length === 0) {
      quoted = true;
    } else if (character === ",") {
      row.push(field);
      field = "";
    } else if (character === "\n" || character === "\r") {
      row.push(field);
      if (row.some((value) => value.trim() !== "")) rows.push(row);
      row = [];
      field = "";
      if (character === "\r" && text[index + 1] === "\n") index += 1;
    } else {
      field += character;
    }
  }

  if (quoted) throw new Error("The CSV contains an unterminated quoted field.");
  row.push(field);
  if (row.some((value) => value.trim() !== "")) rows.push(row);
  return rows;
}

function isIsoDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

export function parseDemandCsv(text) {
  if (typeof text !== "string" || !text.trim()) {
    throw new Error("The CSV file is empty.");
  }

  const rows = csvRecords(text.replace(/^\uFEFF/, ""));
  if (rows.length < 2) {
    throw new Error("The CSV must include a header and at least one demand record.");
  }
  const headers = rows[0].map((header) => header.trim());
  if (new Set(headers).size !== headers.length) {
    throw new Error("The CSV contains duplicate column names.");
  }
  const missing = DEMAND_COLUMNS.filter((column) => !headers.includes(column));
  const unsupported = headers.filter((column) => !DEMAND_COLUMNS.includes(column));
  if (missing.length || unsupported.length) {
    throw new Error(
      `CSV columns must be exactly ${DEMAND_COLUMNS.join(", ")}.`
      + (missing.length ? ` Missing: ${missing.join(", ")}.` : "")
      + (unsupported.length ? ` Unsupported: ${unsupported.join(", ")}.` : ""),
    );
  }

  return rows.slice(1).map((values, index) => {
    if (values.length !== headers.length) {
      throw new Error(`CSV row ${index + 2} has ${values.length} values; expected ${headers.length}.`);
    }
    const record = Object.fromEntries(headers.map((header, column) => [header, values[column].trim()]));
    if (!record.sku_id || !record.destination_id) {
      throw new Error(`CSV row ${index + 2} must include sku_id and destination_id.`);
    }
    if (!isIsoDate(record.demand_date)) {
      throw new Error(`CSV row ${index + 2} demand_date must use a valid YYYY-MM-DD date.`);
    }
    const quantity = Number(record.quantity);
    if (!Number.isFinite(quantity) || quantity < 0) {
      throw new Error(`CSV row ${index + 2} quantity must be a non-negative number.`);
    }
    return { ...record, quantity };
  });
}
