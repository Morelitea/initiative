import { describe, expect, it } from "vitest";

import type { CellValue } from "./coords";
import { createEvaluator } from "./formula";

const sheet = (obj: Record<string, CellValue>) => createEvaluator(new Map(Object.entries(obj)));

/** Evaluate the formula sitting in A1 (key "0:0"), with optional extra
 *  cells in the surrounding map. Returns the CellResult. */
const evalA1 = (formula: string, rest: Record<string, CellValue> = {}) =>
  sheet({ "0:0": formula, ...rest }).evaluate(0, 0);

describe("arithmetic & precedence", () => {
  it("respects operator precedence", () => {
    expect(evalA1("=1+2*3").value).toBe(7);
    expect(evalA1("=(1+2)*3").value).toBe(9);
  });

  it("handles exponentiation and unary minus", () => {
    expect(evalA1("=2^3").value).toBe(8);
    expect(evalA1("=-5+2").value).toBe(-3);
  });

  it("treats percent as divide-by-100", () => {
    expect(evalA1("=50%").value).toBe(0.5);
  });

  it("concatenates with & and compares", () => {
    expect(evalA1('="a"&"b"').value).toBe("ab");
    expect(evalA1("=1<2").value).toBe(true);
    expect(evalA1("=2<=1").value).toBe(false);
  });
});

describe("references & ranges", () => {
  it("resolves cell references", () => {
    // A1 = formula, B1 (0:1) = 2, C1 (0:2) = 3.
    expect(evalA1("=B1+C1", { "0:1": 2, "0:2": 3 }).value).toBe(5);
  });

  it("aggregates over a range", () => {
    const cells = { "0:0": "=SUM(A2:A4)", "1:0": 10, "2:0": 20, "3:0": 30 };
    expect(createEvaluator(new Map(Object.entries(cells))).evaluate(0, 0).value).toBe(60);
  });

  it("AVERAGE / MIN / MAX / COUNT / COUNTA over a range", () => {
    const data = { "1:0": 4, "2:0": 8, "3:0": "x" }; // A2..A4
    expect(evalA1("=AVERAGE(A2:A3)", data).value).toBe(6);
    expect(evalA1("=MIN(A2:A3)", data).value).toBe(4);
    expect(evalA1("=MAX(A2:A3)", data).value).toBe(8);
    expect(evalA1("=COUNT(A2:A4)", data).value).toBe(2); // text not counted
    expect(evalA1("=COUNTA(A2:A4)", data).value).toBe(3); // non-empty counted
  });

  it("treats an empty referenced cell as zero in arithmetic", () => {
    expect(evalA1("=A2+1").value).toBe(1);
  });
});

describe("functions", () => {
  it("IF picks the branch", () => {
    expect(evalA1('=IF(A2>10,"hi","lo")', { "1:0": 20 }).value).toBe("hi");
    expect(evalA1('=IF(A2>10,"hi","lo")', { "1:0": 5 }).value).toBe("lo");
  });

  it("ROUND and ABS", () => {
    expect(evalA1("=ROUND(3.14159,2)").value).toBe(3.14);
    expect(evalA1("=ABS(-5)").value).toBe(5);
  });

  it("returns #NAME? for an unknown function", () => {
    expect(evalA1("=FOO(1)").error).toBe("#NAME?");
  });
});

describe("errors", () => {
  it("divide by zero", () => {
    expect(evalA1("=1/0").error).toBe("#DIV/0!");
  });

  it("non-numeric text in arithmetic", () => {
    expect(evalA1('="abc"+1').error).toBe("#VALUE!");
  });

  it("propagates the first error", () => {
    expect(evalA1("=1/0+1").error).toBe("#DIV/0!");
  });

  it("propagates an error through a reference", () => {
    expect(evalA1("=A2+1", { "1:0": "=1/0" }).error).toBe("#DIV/0!");
  });
});

describe("cycles", () => {
  it("flags a direct self-reference", () => {
    expect(evalA1("=A1+1").error).toBe("#CYCLE!");
  });

  it("flags a mutual reference", () => {
    const cells = { "0:0": "=B1", "0:1": "=A1" };
    const ev = createEvaluator(new Map(Object.entries(cells)));
    expect(ev.evaluate(0, 0).error).toBe("#CYCLE!");
    expect(ev.evaluate(0, 1).error).toBe("#CYCLE!");
  });
});

describe("chained formulas", () => {
  it("evaluates a dependency chain", () => {
    // A1=2, B1==A1*2, C1==B1+1  -> C1 = 5
    const cells = { "0:0": 2, "0:1": "=A1*2", "0:2": "=B1+1" };
    expect(createEvaluator(new Map(Object.entries(cells))).evaluate(0, 2).value).toBe(5);
  });
});

describe("cross-sheet references", () => {
  const workbook = (
    sheets: { id: string; name: string; cells: Record<string, CellValue> }[],
    activeSheetId = sheets[0].id
  ) =>
    createEvaluator({
      sheets: sheets.map((s) => ({ ...s, cells: new Map(Object.entries(s.cells)) })),
      activeSheetId,
    });

  it("resolves a qualified cell reference", () => {
    const e = workbook([
      { id: "s1", name: "Summary", cells: { "0:0": "=Data!A1" } },
      { id: "s2", name: "Data", cells: { "0:0": 42 } },
    ]);
    expect(e.evaluate(0, 0)).toEqual({ value: 42, error: null });
  });

  it("resolves a qualified range through a function", () => {
    const e = workbook([
      { id: "s1", name: "Summary", cells: { "0:0": "=SUM(Data!A1:A3)" } },
      { id: "s2", name: "Data", cells: { "0:0": 1, "1:0": 2, "2:0": 3 } },
    ]);
    expect(e.evaluate(0, 0)).toEqual({ value: 6, error: null });
  });

  it("matches sheet names case-insensitively", () => {
    const e = workbook([
      { id: "s1", name: "Summary", cells: { "0:0": "=dAtA!A1" } },
      { id: "s2", name: "Data", cells: { "0:0": 7 } },
    ]);
    expect(e.evaluate(0, 0).value).toBe(7);
  });

  it("accepts a quoted sheet name", () => {
    const e = workbook([
      { id: "s1", name: "Summary", cells: { "0:0": "='Q1 Actuals'!B2" } },
      { id: "s2", name: "Q1 Actuals", cells: { "1:1": 12 } },
    ]);
    expect(e.evaluate(0, 0).value).toBe(12);
  });

  it("reports #REF! for a sheet that doesn't exist", () => {
    const e = workbook([{ id: "s1", name: "Summary", cells: { "0:0": "=Gone!A1" } }]);
    expect(e.evaluate(0, 0)).toEqual({ value: null, error: "#REF!" });
  });

  it("evaluates a formula on a non-active sheet against its own sheet", () => {
    // B's "=A1" must read B's own A1, not the active sheet's.
    const e = workbook(
      [
        { id: "s1", name: "A", cells: { "0:0": 1 } },
        { id: "s2", name: "B", cells: { "0:0": 100, "0:1": "=A1" } },
      ],
      "s1"
    );
    expect(e.evaluate(0, 1, "s2").value).toBe(100);
  });

  it("chains a formula through another sheet", () => {
    const e = workbook([
      { id: "s1", name: "Summary", cells: { "0:0": "=Data!A1*2" } },
      { id: "s2", name: "Data", cells: { "0:0": "=B1+1", "0:1": 4 } },
    ]);
    expect(e.evaluate(0, 0).value).toBe(10);
  });

  it("detects a cycle that only closes by hopping sheets", () => {
    const e = workbook([
      { id: "s1", name: "One", cells: { "0:0": "=Two!A1" } },
      { id: "s2", name: "Two", cells: { "0:0": "=One!A1" } },
    ]);
    expect(e.evaluate(0, 0).error).toBe("#CYCLE!");
  });
});
