/**
 * Parser-free formula helpers.
 *
 * Kept deliberately separate from ``formula.ts`` (the evaluator) so that
 * ``transform.ts`` — a lightweight pure module run on every row/column
 * insert/delete — can rewrite cell references without pulling the
 * ``fast-formula-parser`` / ``chevrotain`` dependency into its import
 * graph. The only thing shared between the two is the trivial
 * {@link isFormula} predicate.
 *
 * References may be sheet-qualified (``Sheet2!A1``, ``'Q1 Actuals'!A1:B3``).
 * A single {@link matchReferenceAt} probe recognizes both forms, so the
 * rewriting walk and the highlighting walk can never drift apart.
 */

import { type CellValue, colIndexToLetter, letterToColIndex } from "@/lib/spreadsheet/coords";
import { formatSheetPrefix, sheetNameKey, unquoteSheetName } from "@/lib/spreadsheet/sheets";

/** A cell holds a formula when its value is a string beginning with "=". */
export const isFormula = (value: CellValue | undefined): value is string =>
  typeof value === "string" && value.startsWith("=");

// A1-style reference token: optional ``$`` before the column letters and
// before the row digits (``A1``, ``$A1``, ``A$1``, ``$A$1``). Anchored so
// we can probe a single position in the scan below.
const REF_AT_START = /^(\$?)([A-Za-z]+)(\$?)(\d+)/;

// A sheet qualifier: a bare identifier or a ``'``-quoted name (with ``''``
// escaping), followed by ``!``. Mirrors ``quoteSheetName`` in sheets.ts and
// the Sheet / SheetQuoted tokens of the evaluator's grammar.
const SHEET_PREFIX_SRC =
  "(?:'((?:[^']|'')+)'|([A-Za-z_\\u007F-\\uFFFF][A-Za-z0-9_.\\u007F-\\uFFFF]*))!";
const SHEET_PREFIX_AT_START = new RegExp(`^${SHEET_PREFIX_SRC}`);

// Characters that, when they immediately precede or follow a candidate
// match, mean it's part of a longer identifier (a function name like
// ``LOG10``, a defined name, a decimal literal) rather than a standalone
// cell reference. ``(`` after the match marks a function call.
const IDENT_CHAR = /[A-Za-z0-9_.$]/;

/** A matched ref is bogus if what follows it would extend it into a longer
 *  identifier or a function call. ``undefined`` (end of input) is fine. */
const isIdentTail = (c: string | undefined): boolean => {
  const x = c ?? "";
  return x === "(" || IDENT_CHAR.test(x);
};

/** One endpoint of a matched reference: the A1 match plus the sheet
 *  qualifier written in front of it (if any). */
interface RefEndpoint {
  /** The A1 groups: ``[all, colAbs, letters, rowAbs, digits]``. */
  a1: RegExpExecArray;
  /** The qualifier exactly as written, ``!`` included — ``"Sheet2!"``,
   *  ``"'Q1 Actuals'!"`` — or ``""`` for a local reference. */
  prefixText: string;
  /** The decoded (unquoted) sheet name, or ``null`` for a local ref. */
  sheet: string | null;
}

/** A reference token located in a formula body: one cell, or a range whose
 *  qualifier (when present) is written on its first endpoint. */
interface RefMatch {
  start: RefEndpoint;
  /** The second endpoint of a ``A1:B3`` range, else ``null``. */
  end: RefEndpoint | null;
  /** Index in the body just past the whole token. */
  endIndex: number;
}

/** Probe for a (possibly sheet-qualified, possibly ranged) reference
 *  starting at ``i``. Returns ``null`` when there isn't one — including
 *  when the text there is really a function name or a longer identifier. */
const matchEndpointAt = (body: string, i: number): RefEndpoint | null => {
  const prefixMatch = SHEET_PREFIX_AT_START.exec(body.slice(i));
  const prefixText = prefixMatch ? prefixMatch[0] : "";
  const a1 = REF_AT_START.exec(body.slice(i + prefixText.length));
  if (!a1) return null;
  if (isIdentTail(body[i + prefixText.length + a1[0].length])) return null;
  return {
    a1,
    prefixText,
    sheet: prefixMatch ? unquoteSheetName(prefixMatch[1] ?? prefixMatch[2]) : null,
  };
};

const matchReferenceAt = (body: string, i: number): RefMatch | null => {
  // Only probe at an identifier boundary so the ``A1`` inside ``FOO_A1``
  // (or a column-letter run that's really a function name) isn't matched.
  const prev = i > 0 ? body[i - 1] : "";
  if (IDENT_CHAR.test(prev)) return null;
  const start = matchEndpointAt(body, i);
  if (!start) return null;
  const afterStart = i + start.prefixText.length + start.a1[0].length;
  if (body[afterStart] === ":") {
    const end = matchEndpointAt(body, afterStart + 1);
    if (end) {
      return {
        start,
        end,
        endIndex: afterStart + 1 + end.prefixText.length + end.a1[0].length,
      };
    }
  }
  return { start, end: null, endIndex: afterStart };
};

/** Decides whether a rewrite applies to a reference, given the sheet it
 *  names (``null`` = unqualified, i.e. the formula's own sheet). */
export type SheetFilter = (sheet: string | null) => boolean;

/** The default: only unqualified references, which is every reference in a
 *  single-sheet document. */
const LOCAL_ONLY: SheetFilter = (sheet) => sheet === null;

/**
 * Scan a formula and rewrite every cell reference through ``mapSingle``,
 * which maps one matched endpoint to its replacement text (or ``null`` to
 * mark it deleted / off-grid → ``#REF!``). Mappers build that text with
 * {@link emitRef}, which re-attaches the sheet qualifier, so an ordinary
 * coordinate rewrite never has to think about quoting.
 *
 * Ranges (``A1:B10``) are handled as a unit: a ``null`` from *either*
 * endpoint collapses the whole range to a single ``#REF!``
 * (``=SUM(#REF!)``, matching Excel — never the invalid ``=SUM(#REF!:A10)``).
 * The qualifier is dropped along with it: ``#REF!`` is already unambiguous,
 * and ``Sheet2!#REF!`` isn't valid input to the evaluator's grammar.
 *
 * The scan skips double-quoted string literals (with ``""`` escaping) so
 * text like ``="A5 total"`` is never mistaken for a reference, and only
 * probes at identifier boundaries so a function name (``LOG10``) or a name
 * like ``FOO_A1`` isn't rewritten. Non-formula input is returned unchanged.
 */
const scanReferences = (
  formula: string,
  mapSingle: (endpoint: RefEndpoint) => string | null
): string => {
  if (!isFormula(formula)) return formula;
  const body = formula.slice(1);
  let out = "=";
  let i = 0;
  let inQuote = false;

  while (i < body.length) {
    const ch = body[i];

    if (inQuote) {
      out += ch;
      if (ch === '"') {
        // Doubled quote inside a string is an escaped quote, not the end.
        if (body[i + 1] === '"') {
          out += '"';
          i += 2;
          continue;
        }
        inQuote = false;
      }
      i++;
      continue;
    }

    if (ch === '"') {
      inQuote = true;
      out += ch;
      i++;
      continue;
    }

    const match = matchReferenceAt(body, i);
    if (match) {
      const start = mapSingle(match.start);
      if (match.end) {
        const end = mapSingle(match.end);
        // A deleted/off-grid endpoint collapses the whole range (Excel).
        out += start === null || end === null ? "#REF!" : `${start}:${end}`;
      } else {
        out += start ?? "#REF!";
      }
      i = match.endIndex;
      continue;
    }

    out += ch;
    i++;
  }

  return out;
};

/** Re-assemble a reference from its (possibly rewritten) parts: the sheet
 *  qualifier as written, then the A1 text. ``null`` propagates so a caller
 *  can spell "this reference no longer exists". */
const emitRef = (endpoint: RefEndpoint, a1: string | null, prefix?: string): string | null =>
  a1 === null ? null : `${prefix ?? endpoint.prefixText}${a1}`;

/**
 * Rewrite cell references in a formula along ``axis`` using ``mapIndex`` —
 * the exact old-index → new-index mapper that ``transformSheet`` builds for
 * an insert/delete. References on the inactive axis are left untouched; a
 * reference whose active-axis line was deleted (``mapIndex`` returns
 * ``null``) becomes ``#REF!``.
 *
 * ``applies`` selects which references the shift reaches, by the sheet they
 * name. It defaults to unqualified references only — right for a formula
 * sitting on the sheet being transformed in a single-sheet document. A
 * workbook passes a filter that also matches the transformed sheet's own
 * name, and a second pass over the *other* sheets passes one that matches
 * only that name (see ``transform.ts``).
 *
 * Ranges shrink when an interior line is deleted and collapse to ``#REF!``
 * when an endpoint's line is deleted. ``$`` absolute markers are preserved
 * verbatim, but the index *still moves* — an insert above ``$A$5`` pushes
 * it to ``$A$6`` because the content it points at shifted. (Contrast
 * {@link translateFormula}, where ``$`` pins the reference in place.)
 */
export const shiftFormulaReferences = (
  formula: string,
  axis: "row" | "col",
  mapIndex: (i: number) => number | null,
  applies: SheetFilter = LOCAL_ONLY
): string =>
  scanReferences(formula, (endpoint) =>
    emitRef(
      endpoint,
      applies(endpoint.sheet) ? mapRef(endpoint.a1, axis, mapIndex) : endpoint.a1[0]
    )
  );

/**
 * Translate every *relative* reference in a formula by ``rowDelta`` /
 * ``colDelta`` — the copy/fill semantics of a spreadsheet. A ``$`` marker
 * pins that component in place (``$A$1`` never moves; ``A$1`` moves only by
 * column; ``$A1`` only by row). A reference pushed off the grid (negative
 * row or column) becomes ``#REF!``, and a range collapses to ``#REF!`` if
 * either endpoint does. Non-formula input is returned unchanged.
 *
 * Sheet-qualified references translate their coordinates like any other and
 * keep pointing at the same sheet, matching Excel: copying ``=Sheet2!A1``
 * one row down gives ``=Sheet2!A2``.
 */
export const translateFormula = (formula: string, rowDelta: number, colDelta: number): string =>
  scanReferences(formula, (endpoint) =>
    emitRef(endpoint, mapRefTranslate(endpoint.a1, rowDelta, colDelta))
  );

/** Rewrite one matched reference along ``axis``; ``null`` if its line was
 *  deleted (the caller turns that into ``#REF!``). */
const mapRef = (
  m: RegExpExecArray,
  axis: "row" | "col",
  mapIndex: (i: number) => number | null
): string | null => {
  const [, colAbs, letters, rowAbs, digits] = m;
  if (axis === "col") {
    const mapped = mapIndex(letterToColIndex(letters));
    return mapped === null ? null : `${colAbs}${colIndexToLetter(mapped)}${rowAbs}${digits}`;
  }
  const mapped = mapIndex(Number(digits) - 1);
  return mapped === null ? null : `${colAbs}${letters}${rowAbs}${mapped + 1}`;
};

/** Translate one matched reference by ``rowDelta`` / ``colDelta``, leaving
 *  ``$``-pinned components untouched; ``null`` if pushed off the grid (the
 *  caller turns that into ``#REF!``). */
const mapRefTranslate = (m: RegExpExecArray, rowDelta: number, colDelta: number): string | null => {
  const [, colAbs, letters, rowAbs, digits] = m;
  const col = letterToColIndex(letters) + (colAbs ? 0 : colDelta);
  const row = Number(digits) - 1 + (rowAbs ? 0 : rowDelta);
  if (row < 0 || col < 0) return null;
  return `${colAbs}${colIndexToLetter(col)}${rowAbs}${row + 1}`;
};

/** A {@link SheetFilter} matching a formula's own sheet: unqualified
 *  references, plus ones that name that sheet explicitly. */
export const ownSheetFilter = (name: string): SheetFilter => {
  const key = sheetNameKey(name);
  return (sheet) => sheet === null || sheetNameKey(sheet) === key;
};

/** A {@link SheetFilter} matching only references that explicitly name
 *  ``name`` — what a formula on some *other* sheet uses. */
export const otherSheetFilter = (name: string): SheetFilter => {
  const key = sheetNameKey(name);
  return (sheet) => sheet !== null && sheetNameKey(sheet) === key;
};

/**
 * Rewrite the sheet qualifiers in a formula after a sheet is renamed.
 * References that named ``from`` are re-emitted naming ``to`` (re-quoted as
 * the new name requires); everything else is left byte-identical. Returns
 * the formula unchanged when it names no such sheet.
 */
export const renameSheetReferences = (formula: string, from: string, to: string): string => {
  if (!isFormula(formula)) return formula;
  const fromKey = sheetNameKey(from);
  const renamed = formatSheetPrefix(to);
  return scanReferences(formula, (endpoint) =>
    emitRef(
      endpoint,
      endpoint.a1[0],
      endpoint.sheet !== null && sheetNameKey(endpoint.sheet) === fromKey ? renamed : undefined
    )
  );
};

// ---------------------------------------------------------------------------
// Reference extraction (read-only) for the formula editor's live highlights.
// ---------------------------------------------------------------------------

/**
 * Palette for the editor's reference highlights. The same index colors a
 * reference's outline box on the grid and its text in the formula input, and
 * is reused for repeated identical references (Excel behavior). Index with
 * ``colorIndex % FORMULA_REF_COLORS.length``.
 */
export const FORMULA_REF_COLORS = [
  "#1a73e8",
  "#188038",
  "#a142f4",
  "#e8710a",
  "#d93025",
  "#12a4af",
  "#c5221f",
  "#9334e6",
];

/** One reference (or ``A1:B3`` range) located inside a formula string. */
export interface FormulaRefToken {
  /** The matched text, e.g. ``A1``, ``$A$1:B3``, or ``Sheet2!A1``. */
  text: string;
  /** Character offset of the token in the full formula (including the leading "="). */
  start: number;
  /** Exclusive end offset. */
  end: number;
  /** Normalized bounding box (0-based, top-left .. bottom-right). */
  r1: number;
  c1: number;
  r2: number;
  c2: number;
  /** The sheet the reference names, or ``null`` when it's local to the
   *  formula's own sheet. The grid only outlines a token whose sheet is
   *  the one currently on screen. */
  sheet: string | null;
  /** Stable index into {@link FORMULA_REF_COLORS}, shared by identical refs. */
  colorIndex: number;
}

/** Resolve a matched A1 reference to 0-based coords, or ``null`` if off-grid. */
const refCoords = (m: RegExpExecArray): { row: number; col: number } | null => {
  const col = letterToColIndex(m[2]);
  const row = Number(m[4]) - 1;
  if (col < 0 || row < 0) return null;
  return { row, col };
};

/**
 * Locate every reference / range in a formula and return its character span
 * and grid box, for the editor's live highlighting. Shares
 * {@link matchReferenceAt} with {@link scanReferences}, so the two walks
 * agree by construction; off-grid references are simply omitted rather than
 * collapsed to ``#REF!``. Non-formula input yields an empty array.
 *
 * ``colorIndex`` is assigned per unique reference text in order of first
 * appearance, so ``=A1+A1`` colors both ``A1`` tokens identically.
 */
export const extractReferences = (formula: string): FormulaRefToken[] => {
  if (!isFormula(formula)) return [];
  const body = formula.slice(1);
  const raw: Omit<FormulaRefToken, "colorIndex">[] = [];
  let i = 0;
  let inQuote = false;

  while (i < body.length) {
    const ch = body[i];

    if (inQuote) {
      if (ch === '"') {
        if (body[i + 1] === '"') {
          i += 2;
          continue;
        }
        inQuote = false;
      }
      i++;
      continue;
    }

    if (ch === '"') {
      inQuote = true;
      i++;
      continue;
    }

    const match = matchReferenceAt(body, i);
    if (match) {
      const first = refCoords(match.start.a1);
      const second = match.end ? refCoords(match.end.a1) : first;
      if (first && second) {
        raw.push({
          text: body.slice(i, match.endIndex),
          start: i + 1,
          end: match.endIndex + 1,
          r1: Math.min(first.row, second.row),
          c1: Math.min(first.col, second.col),
          r2: Math.max(first.row, second.row),
          c2: Math.max(first.col, second.col),
          sheet: match.start.sheet,
        });
      }
      i = match.endIndex;
      continue;
    }

    i++;
  }

  const colorByText = new Map<string, number>();
  return raw.map((t) => {
    let colorIndex = colorByText.get(t.text);
    if (colorIndex === undefined) {
      colorIndex = colorByText.size;
      colorByText.set(t.text, colorIndex);
    }
    return { ...t, colorIndex };
  });
};

/**
 * Where (if anywhere) a clicked cell's reference should land in the formula
 * draft, given the caret position — the editor's "point mode" decision.
 *
 * - ``insert``: the caret follows a token that expects an operand (``=``, an
 *   operator, ``(``, ``,`` or ``:``) — splice a fresh reference there.
 * - ``replace``: the caret sits just after a reference that itself follows an
 *   operand-accepting token — clicking moves that reference (Excel behavior).
 * - ``none``: the caret is mid-literal/value — the click should commit the
 *   edit normally instead.
 */
export type InsertTarget =
  | { kind: "none" }
  | { kind: "insert"; at: number }
  | { kind: "replace"; start: number; end: number };

// Final char of the (whitespace-trimmed) text before the caret that means a
// reference may follow.
const REF_ACCEPTING_END = /[=(,:+\-*/^&<>%]$/;
// A trailing reference (or range), sheet qualifier included, at the end of
// the pre-caret text.
const TRAILING_A1 = `(?:${SHEET_PREFIX_SRC})?\\$?[A-Za-z]+\\$?\\d+`;
const TRAILING_REF = new RegExp(`(${TRAILING_A1}(?::${TRAILING_A1})?)$`);

export const referenceInsertTarget = (draft: string, caret: number): InsertTarget => {
  if (!isFormula(draft)) return { kind: "none" };
  const before = draft.slice(0, caret);
  const trimmed = before.replace(/\s+$/, "");
  if (REF_ACCEPTING_END.test(trimmed)) return { kind: "insert", at: caret };
  const refMatch = TRAILING_REF.exec(trimmed);
  if (refMatch) {
    const start = trimmed.length - refMatch[1].length;
    const charBefore = start > 0 ? trimmed[start - 1] : "";
    // The leading "=" (start === 1) or any operand-accepting char before the
    // reference means the user is still pointing — clicking moves the ref.
    if (start === 1 || REF_ACCEPTING_END.test(charBefore)) {
      return { kind: "replace", start, end: trimmed.length };
    }
  }
  return { kind: "none" };
};
