import { describe, expect, it } from "vitest";
import { parseDemandCsv } from "./datasetUpload";

describe("demand CSV upload parser", () => {
  it("parses reordered columns and quoted identifiers", () => {
    const rows = parseDemandCsv(
      'quantity,demand_date,destination_id,sku_id\r\n12.5,2026-10-20,"North, DC","SKU-1"\r\n',
    );

    expect(rows).toEqual([{
      quantity: 12.5,
      demand_date: "2026-10-20",
      destination_id: "North, DC",
      sku_id: "SKU-1",
    }]);
  });

  it.each([
    ["", "empty"],
    ["sku_id,destination_id,demand_date,quantity", "header"],
    ["sku_id,destination_id,demand_date,quantity\nA,B,2026-02-30,1", "valid YYYY-MM-DD"],
    ["sku_id,destination_id,demand_date,quantity\nA,B,2026-10-20,-1", "non-negative"],
    ['sku_id,destination_id,demand_date,quantity\nA,B,2026-10-20,"1', "unterminated"],
  ])("rejects invalid CSV input", (input, message) => {
    expect(() => parseDemandCsv(input)).toThrow(message);
  });
});
