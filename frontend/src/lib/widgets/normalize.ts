/**
 * From what an endpoint answered to what a widget reads.
 *
 * Two producers, one envelope. A statement's columns arrive already typed — the
 * server described them rather than guessing from the first row — and a
 * spreadsheet range's do not, so its types are read off the values. Everything
 * downstream of here sees the same {@link TabularData} and never learns which
 * it was handed.
 */

import type { DocumentRead } from "@/api/generated/initiativeAPI.schemas";
import { keyOf, parseA1Range } from "@/lib/spreadsheet/coords";

import type { CellValue, ColumnType, DataColumn, WidgetData, WidgetSource } from "./dataShapes";

/** A cell, in the three shapes a JSON value can usefully be.
 *
 *  Anything else is nothing: a widget can draw a string, a number or a yes/no,
 *  and writing an object out would put "[object Object]" in a table rather than
 *  showing that the cell held nothing it could render. */
const cell = (value: unknown): CellValue => {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return value;
  }
  return null;
};

/**
 * A statement's answer, held to its own described width.
 *
 * A row longer than the described columns is cut and a shorter one padded, so a
 * widget indexing by column position can never read past the end of a row.
 */
export const normalizeQueryRows = (
  columns: DataColumn[],
  rows: unknown[][]
): { columns: DataColumn[]; rows: CellValue[][] } => ({
  columns,
  rows: rows.map((row) => columns.map((_column, index) => cell(row[index]))),
});

/**
 * What a column of sheet cells holds.
 *
 * Read off the values because a spreadsheet declares nothing: a column whose
 * every filled cell is a number is a number, and anything else is text. Blank
 * cells are skipped rather than counted as text, so one empty row does not stop
 * a column of figures being figures.
 */
const sniff = (rows: CellValue[][], index: number): ColumnType => {
  let seen = false;
  for (const row of rows) {
    const value = row[index];
    if (value === null || value === "") continue;
    seen = true;
    if (typeof value !== "number") return "text";
  }
  return seen ? "number" : "text";
};

interface SheetLike {
  id?: string;
  name?: string;
  cells?: Record<string, unknown>;
}

export const normalizeSheetRange = (
  document: DocumentRead,
  sheetName: string | null | undefined,
  range: string | null | undefined
): { columns: DataColumn[]; rows: CellValue[][] } | null => {
  const content = document.content as { sheets?: SheetLike[] } | null;
  const sheets = content?.sheets ?? [];
  if (!sheets.length) return null;

  const sheet = sheetName
    ? sheets.find((s) => s.name === sheetName || s.id === sheetName)
    : sheets[0];
  if (!sheet?.cells) return null;

  const box = range ? parseA1Range(range) : null;
  if (!box) return null;

  const rows: CellValue[][] = [];
  for (let row = box.r1; row <= box.r2; row++) {
    const line: CellValue[] = [];
    for (let col = box.c1; col <= box.c2; col++) {
      const value = sheet.cells[keyOf(row, col)];
      line.push(cell(value));
    }
    rows.push(line);
  }
  if (!rows.length) return { columns: [], rows: [] };

  const [firstRow] = rows;
  const headerLooksLikeLabels =
    rows.length > 1 && firstRow.every((cell) => typeof cell === "string" && cell !== "");

  const body = headerLooksLikeLabels ? rows.slice(1) : rows;
  const names = headerLooksLikeLabels
    ? firstRow.map(String)
    : firstRow.map((_, index) => `Column ${index + 1}`);
  return {
    columns: names.map((name, index) => ({ name, type: sniff(body, index) })),
    rows: body,
  };
};

/** The envelope for a binding we fetched nothing for — one whose parameters the
 *  instance config has not filled in yet. */
export const emptyDataFor = (source: WidgetSource): WidgetData =>
  source === "app"
    ? { source: "app", rows: [], values: {} }
    : { source: "rows", columns: [], rows: [] };
