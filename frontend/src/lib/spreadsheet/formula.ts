/**
 * Formula evaluation for spreadsheet cells.
 *
 * Formulas live in the cell map as ordinary ``"=..."`` strings (see
 * {@link isFormula}); this module turns one into its computed value. We
 * lean on ``fast-formula-parser`` for the parsing + Excel function set
 * (SUM, AVERAGE, IF, …) and supply the surrounding machinery it lacks:
 * resolving A1 references against our sparse ``r:c`` maps, recursively
 * evaluating referenced formula cells, memoizing results, and detecting
 * circular references.
 *
 * A workbook has several sheets, so a reference resolves in two steps: the
 * sheet qualifier (``Sheet2!A1``, absent for a local reference — the parser
 * fills in the formula's own sheet) picks the cell map, then the
 * coordinates pick the cell. Everything downstream — the memo cache, the
 * cycle-detection stack — is keyed by *(sheet, row, col)*, so a cycle that
 * only closes by hopping sheets (``Sheet1!A1 = Sheet2!A1 = Sheet1!A1``) is
 * caught exactly like a local one.
 *
 * {@link createEvaluator} is bound to one immutable snapshot of the whole
 * workbook. The editor rebuilds it whenever any sheet's cells change (every
 * local edit, remote peer write, or undo/redo produces fresh maps), so a
 * ``useMemo`` keyed on those maps recomputes for free. Each cell is
 * evaluated at most once per snapshot thanks to the result cache.
 *
 * Evaluators come and go on every edit; the parsers they use do not. See
 * {@link PARSER_POOL} for why a parser is per *nesting level* rather than
 * per evaluator, and why the pool outlives them all.
 */

import FormulaParser, { FormulaError, FormulaHelpers, Types } from "fast-formula-parser";

import { type CellValue, keyOf } from "@/lib/spreadsheet/coords";
import { isFormula } from "@/lib/spreadsheet/formula-refs";
import { DEFAULT_SHEET_ID, type SheetId, sheetNameKey } from "@/lib/spreadsheet/sheets";

export { isFormula };

/** Collect the numbers a variadic argument list flattens to — literals,
 *  cell references and ranges alike, which is what makes ``MEDIAN(A1:A9)``
 *  and ``MEDIAN(1,2,3)`` the same call. */
const numbersOf = (params: unknown[]): number[] => {
  const out: number[] = [];
  FormulaHelpers.flattenParams(params, Types.NUMBER, true, (item) => {
    if (typeof item === "number" && Number.isFinite(item)) out.push(item);
  });
  return out;
};

/** Everything an argument list flattens to, types intact — for the
 *  functions that count or compare rather than add. */
const valuesOf = (params: unknown[]): unknown[] => {
  const out: unknown[] = [];
  FormulaHelpers.flattenParams(params, null, true, (item) => out.push(item));
  return out;
};

/** The parser hands functions on its context list itself as the first
 *  argument. Only the two members our overrides use are named here. */
interface FunctionContext {
  /** Resolve an unretrieved reference argument to its value(s). */
  retrieveRef: (valueOrRef: unknown) => unknown;
  utils: { extractRefValue: (param: unknown) => { val: unknown; isArray: boolean } };
}

const str = (param: unknown, fallback?: string): string =>
  String(FormulaHelpers.accept(param, Types.STRING, fallback));
const num = (param: unknown, fallback?: number): number =>
  Number(FormulaHelpers.accept(param, Types.NUMBER, fallback));

/** Sum of squared deviations — the shared half of VAR and STDEV. */
const sumSquaredDeviations = (values: number[]): number => {
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  return values.reduce((acc, v) => acc + (v - mean) ** 2, 0);
};

const variance = (values: number[], sample: boolean): number | FormulaError => {
  const n = values.length;
  if (sample ? n < 2 : n < 1) return FormulaError.DIV0;
  return sumSquaredDeviations(values) / (sample ? n - 1 : n);
};

// fast-formula-parser ships ~280 of Excel's functions, but a number of
// everyday ones are unimplemented stubs or absent altogether. They're
// registered here through the same FormulaHelpers plumbing the built-ins
// use, so they accept literals, cell references and ranges alike.
const CUSTOM_FUNCTIONS = {
  // --- aggregates --------------------------------------------------------
  MIN: (...numbers: unknown[]): number => {
    const values = numbersOf(numbers);
    return values.length === 0 ? 0 : Math.min(...values); // Excel: MIN of nothing is 0
  },
  MAX: (...numbers: unknown[]): number => {
    const values = numbersOf(numbers);
    return values.length === 0 ? 0 : Math.max(...values);
  },
  COUNTA: (...ranges: unknown[]): number =>
    valuesOf(ranges).filter((item) => item !== null && item !== undefined && item !== "").length,
  COUNTBLANK: (...ranges: unknown[]): number =>
    valuesOf(ranges).filter((item) => item === null || item === undefined || item === "").length,
  MEDIAN: (...numbers: unknown[]): number | FormulaError => {
    const values = numbersOf(numbers).sort((a, b) => a - b);
    if (values.length === 0) return FormulaError.NUM;
    const mid = Math.floor(values.length / 2);
    return values.length % 2 === 1 ? values[mid] : (values[mid - 1] + values[mid]) / 2;
  },
  // ``k`` counts from the largest for LARGE and the smallest for SMALL, and
  // is 1-based in both.
  LARGE: (array: unknown, k: unknown): number | FormulaError => {
    const values = numbersOf([array]).sort((a, b) => b - a);
    const at = Math.trunc(num(k));
    return at >= 1 && at <= values.length ? values[at - 1] : FormulaError.NUM;
  },
  SMALL: (array: unknown, k: unknown): number | FormulaError => {
    const values = numbersOf([array]).sort((a, b) => a - b);
    const at = Math.trunc(num(k));
    return at >= 1 && at <= values.length ? values[at - 1] : FormulaError.NUM;
  },
  /** Position in the sorted order, ties sharing the best rank. ``order``
   *  0 (or omitted) ranks largest first, anything else smallest first. */
  RANK: (value: unknown, array: unknown, order?: unknown): number | FormulaError => {
    const target = num(value);
    const descending = num(order, 0) === 0;
    const values = numbersOf([array]);
    if (!values.includes(target)) return FormulaError.NA;
    const ahead = values.filter((v) => (descending ? v > target : v < target)).length;
    return ahead + 1;
  },
  STDEV: (...numbers: unknown[]): number | FormulaError => {
    const result = variance(numbersOf(numbers), true);
    return result instanceof FormulaError ? result : Math.sqrt(result);
  },
  STDEVP: (...numbers: unknown[]): number | FormulaError => {
    const result = variance(numbersOf(numbers), false);
    return result instanceof FormulaError ? result : Math.sqrt(result);
  },
  VAR: (...numbers: unknown[]): number | FormulaError => variance(numbersOf(numbers), true),
  VARP: (...numbers: unknown[]): number | FormulaError => variance(numbersOf(numbers), false),

  // --- text --------------------------------------------------------------
  UPPER: (text: unknown): string => str(text).toUpperCase(),
  /** Replace occurrences of ``oldText``; with ``instance`` given, only that
   *  one (1-based). Case-sensitive, like Excel's. */
  SUBSTITUTE: (
    text: unknown,
    oldText: unknown,
    newText: unknown,
    instance?: unknown
  ): string | FormulaError => {
    const haystack = str(text);
    const needle = str(oldText);
    const replacement = str(newText);
    if (needle === "") return haystack;
    const which = instance === undefined ? null : Math.trunc(num(instance));
    if (which !== null && which < 1) return FormulaError.VALUE;
    let out = "";
    let at = 0;
    let seen = 0;
    for (;;) {
      const hit = haystack.indexOf(needle, at);
      if (hit < 0) break;
      seen++;
      const take = which === null || seen === which;
      out += haystack.slice(at, hit) + (take ? replacement : needle);
      at = hit + needle.length;
    }
    return out + haystack.slice(at);
  },
  /** Join with a delimiter, optionally dropping the empties. */
  TEXTJOIN: (delimiter: unknown, ignoreEmpty: unknown, ...texts: unknown[]): string => {
    const separator = str(delimiter, "");
    const skipEmpty = FormulaHelpers.accept(ignoreEmpty, Types.BOOLEAN, true) !== false;
    const parts = valuesOf(texts)
      .map((item) => (item === null || item === undefined ? "" : String(item)))
      .filter((part) => !skipEmpty || part !== "");
    return parts.join(separator);
  },
  /** Text that reads as a number, as a number. */
  VALUE: (text: unknown): number | FormulaError => {
    const raw = FormulaHelpers.accept(text, null);
    if (typeof raw === "number") return raw;
    const trimmed = String(raw ?? "").trim();
    if (trimmed === "") return FormulaError.VALUE;
    const parsed = Number(trimmed.replace(/,/g, ""));
    return Number.isFinite(parsed) ? parsed : FormulaError.VALUE;
  },
  /** Case-*insensitive* position of one string inside another — the
   *  difference from FIND, which the shipped implementation loses. */
  SEARCH: (findText: unknown, withinText: unknown, startNum?: unknown): number | FormulaError => {
    const needle = str(findText).toLowerCase();
    const haystack = str(withinText);
    const from = Math.trunc(num(startNum, 1));
    if (from < 1 || from > haystack.length) return FormulaError.VALUE;
    const at = haystack.toLowerCase().indexOf(needle, from - 1);
    return at < 0 ? FormulaError.VALUE : at + 1;
  },

  // --- lookup & logic ----------------------------------------------------
  /** Position of a value in a one-dimensional range. ``matchType`` 0 is an
   *  exact match; 1 (the default) and -1 want sorted data and take the
   *  closest value not past the target. */
  MATCH: (lookup: unknown, array: unknown, matchType?: unknown): number | FormulaError => {
    const target = FormulaHelpers.accept(lookup, null);
    const values = valuesOf([array]);
    const mode = Math.trunc(num(matchType, 1));
    const same = (a: unknown, b: unknown) =>
      typeof a === "string" && typeof b === "string"
        ? a.toLowerCase() === b.toLowerCase()
        : a === b;
    if (mode === 0) {
      const at = values.findIndex((v) => same(v, target));
      return at < 0 ? FormulaError.NA : at + 1;
    }
    let best = -1;
    for (let i = 0; i < values.length; i++) {
      const v = values[i];
      if (typeof v !== "number" || typeof target !== "number") continue;
      if (mode > 0 ? v <= target : v >= target) best = i;
      else break;
    }
    return best < 0 ? FormulaError.NA : best + 1;
  },
  /**
   * Value at a position in a range.
   *
   * The shipped implementation answers with a freshly built cell reference
   * that carries no sheet, so the result is read from whichever sheet the
   * *formula* lives on — ``=INDEX(Data!A2:A9,4)`` written on another tab
   * returns that tab's A5. This one resolves the range to its values first,
   * which keeps the sheet the reference named.
   *
   * INDEX is on the library's fixed list of functions that receive their
   * arguments unretrieved, hence the context and the manual unwrapping.
   * Excel's rarely-used reference form (an INDEX as a range endpoint) is
   * not supported: this always yields a value.
   */
  INDEX: (context: unknown, ranges: unknown, rowNum: unknown, colNum: unknown): unknown => {
    const ctx = context as FunctionContext;
    const asIndex = (param: unknown, fallback: number): number => {
      if (param === null || param === undefined) return fallback;
      const { val, isArray } = ctx.utils.extractRefValue(param);
      return Math.trunc(
        Number(FormulaHelpers.accept({ value: val, isArray }, Types.NUMBER, fallback))
      );
    };
    const row = asIndex(rowNum, 1);
    // 0 means "not given" — Excel's own ``column_num`` is 1-based.
    const col = asIndex(colNum, 0);
    const data = ctx.retrieveRef(ranges);
    const grid: unknown[][] = Array.isArray(data)
      ? (data as unknown[][]).map((line) => (Array.isArray(line) ? line : [line]))
      : [[data]];
    if (grid.length === 0) return FormulaError.REF;

    // A single row takes its one index along the columns, matching Excel's
    // shorthand for a horizontal range.
    const [r, c] = col === 0 && grid.length === 1 ? [1, row] : col === 0 ? [row, 1] : [row, col];
    const line = grid[r - 1];
    if (!line || c < 1 || c > line.length) return FormulaError.REF;
    return line[c - 1];
  },
  /** Pick the ``index``-th of the following arguments, 1-based.
   *
   *  CHOOSE is on the library's fixed list of context-taking functions, so
   *  it is handed the parser context ahead of its own arguments however it
   *  was registered — hence the leading parameter we don't use. */
  CHOOSE: (_context: unknown, index: unknown, ...choices: unknown[]): unknown => {
    const at = Math.trunc(num(index));
    if (at < 1 || at > choices.length) return FormulaError.VALUE;
    return FormulaHelpers.accept(choices[at - 1], null);
  },
  /** Compare one value against condition/result pairs, with an optional
   *  trailing default. */
  SWITCH: (value: unknown, ...rest: unknown[]): unknown => {
    const target = FormulaHelpers.accept(value, null);
    const pairs = Math.floor(rest.length / 2);
    for (let i = 0; i < pairs; i++) {
      if (FormulaHelpers.accept(rest[i * 2], null) === target) {
        return FormulaHelpers.accept(rest[i * 2 + 1], null);
      }
    }
    // An odd argument left over is the default.
    return rest.length % 2 === 1
      ? FormulaHelpers.accept(rest[rest.length - 1], null)
      : FormulaError.NA;
  },

  // A formula reads the workbook and nothing else. The library ships two
  // functions that reach outside it; both are answered as unknown names, the
  // same as any function we don't implement.
  WEBSERVICE: (): FormulaError => FormulaError.NAME,
  FILTERXML: (): FormulaError => FormulaError.NAME,
};

/** The result of evaluating a cell: a scalar value, or an Excel-style
 *  error token (``error`` non-null, ``value`` null). */
export interface CellResult {
  value: CellValue;
  error: string | null;
}

export interface Evaluator {
  /** Evaluate the cell at (0-based) ``row`` / ``col``. Non-formula cells
   *  return their stored scalar with no error. ``sheetId`` defaults to the
   *  workbook's active sheet. */
  evaluate: (row: number, col: number, sheetId?: SheetId) => CellResult;
}

/** One sheet as the evaluator sees it: an identity plus a cell map. */
export interface EvaluatorSheet {
  id: SheetId;
  /** The user-facing name a cross-sheet reference spells. */
  name: string;
  cells: ReadonlyMap<string, CellValue>;
}

export interface EvaluatorWorkbook {
  sheets: readonly EvaluatorSheet[];
  /** The sheet an unqualified reference resolves against. */
  activeSheetId: SheetId;
}

/** Our own circular-reference token (Excel surfaces this as a warning, not
 *  a cell error, but a token keeps it visible and out of the math). */
const CYCLE_ERROR = "#CYCLE!";
const GENERIC_ERROR = "#ERROR!";
/** A reference naming a sheet that doesn't exist (renamed away, deleted). */
const REF_ERROR = "#REF!";
/** Sheet name used when the caller hands us a bare cell map (a single
 *  anonymous sheet — the shape most unit tests want). */
const LONE_SHEET_NAME = "Sheet1";

const isScalar = (v: unknown): v is CellValue =>
  v == null || typeof v === "string" || typeof v === "number" || typeof v === "boolean";

/** What a pooled parser calls back into: one evaluator's cell resolver,
 *  taking the sheet name a reference named (``undefined`` when it named
 *  none) and 0-based coordinates. */
type CellResolver = (
  sheetName: string | undefined,
  row: number,
  col: number
) => CellValue | FormulaError;

/**
 * The parser pool.
 *
 * ``FormulaParser`` keeps the formula's position and the token stream on the
 * instance for the duration of a parse, so one parser cannot be inside two
 * parses at once — and resolving a reference to another formula cell is
 * exactly that: the outer parse is suspended in a hook while the inner one
 * runs. Each nesting level therefore gets its own parser.
 *
 * The pool is module-level rather than per-evaluator because building a
 * parser costs milliseconds (it constructs a grammar) and an evaluator is
 * rebuilt on every edit. To let one pool serve every evaluator, the hooks
 * dispatch through {@link activeResolver} rather than closing over one
 * evaluator: evaluation is synchronous and single-threaded, so the resolver
 * in force is simply whichever evaluator is currently parsing, saved and
 * restored around each parse.
 */
const PARSER_POOL: FormulaParser[] = [];
let activeResolver: CellResolver | null = null;
let parseDepth = 0;

const resolveThroughActive = (
  sheetName: string | undefined,
  row: number,
  col: number
): CellValue | FormulaError =>
  activeResolver ? activeResolver(sheetName, row, col) : new FormulaError(REF_ERROR);

const parserForDepth = (depth: number): FormulaParser => {
  const pooled = PARSER_POOL[depth];
  if (pooled) return pooled;
  const created = new FormulaParser({
    onCell: ({ sheet, row, col }) => resolveThroughActive(sheet, row - 1, col - 1),
    onRange: ({ sheet, from, to }) => {
      const grid: (CellValue | FormulaError)[][] = [];
      for (let r = from.row; r <= to.row; r++) {
        const line: (CellValue | FormulaError)[] = [];
        for (let c = from.col; c <= to.col; c++)
          line.push(resolveThroughActive(sheet, r - 1, c - 1));
        grid.push(line);
      }
      return grid;
    },
    functions: CUSTOM_FUNCTIONS,
  });
  PARSER_POOL[depth] = created;
  return created;
};

const asWorkbook = (
  source: ReadonlyMap<string, CellValue> | EvaluatorWorkbook
): EvaluatorWorkbook =>
  source instanceof Map
    ? {
        sheets: [{ id: DEFAULT_SHEET_ID, name: LONE_SHEET_NAME, cells: source }],
        activeSheetId: DEFAULT_SHEET_ID,
      }
    : (source as EvaluatorWorkbook);

export const createEvaluator = (
  source: ReadonlyMap<string, CellValue> | EvaluatorWorkbook
): Evaluator => {
  const workbook = asWorkbook(source);
  const byId = new Map<SheetId, EvaluatorSheet>();
  const idByName = new Map<string, SheetId>();
  for (const sheet of workbook.sheets) {
    byId.set(sheet.id, sheet);
    // First sheet wins a duplicated name — names are kept unique on write,
    // so this only matters for a snapshot that arrived malformed.
    if (!idByName.has(sheetNameKey(sheet.name))) idByName.set(sheetNameKey(sheet.name), sheet.id);
  }
  const activeId = byId.has(workbook.activeSheetId)
    ? workbook.activeSheetId
    : (workbook.sheets[0]?.id ?? DEFAULT_SHEET_ID);

  const cache = new Map<string, CellResult>();
  const visiting = new Set<string>();

  // (sheet, row, col) → cache/stack key. The sheet id can't contain the
  // separator (it's minted from hex), so the composition is unambiguous.
  const cellKey = (sheetId: SheetId, row: number, col: number): string =>
    `${sheetId} ${keyOf(row, col)}`;

  // The sheet whose formula is currently being parsed. The library fills a
  // bare reference's ``sheet`` in from the position we pass, so this is
  // only the belt-and-braces fallback — but "the formula's own sheet" is
  // the right answer, and the *active* sheet would silently be the wrong
  // one for a formula the user isn't looking at.
  let currentSheetId: SheetId = activeId;

  // Resolve one cell to the value (or FormulaError) the parser expects.
  // Errors are returned as FormulaError instances so the library
  // propagates them through arithmetic, exactly like Excel.
  const resolve = (
    sheetName: string | undefined,
    row: number,
    col: number
  ): CellValue | FormulaError => {
    const sheetId =
      sheetName === undefined ? currentSheetId : idByName.get(sheetNameKey(sheetName));
    if (sheetId === undefined) return new FormulaError(REF_ERROR);
    const res = evaluate(row, col, sheetId);
    if (res.error) return new FormulaError(res.error);
    return res.value;
  };

  function evaluate(row: number, col: number, sheetId: SheetId = activeId): CellResult {
    const sheet = byId.get(sheetId);
    if (!sheet) return { value: null, error: REF_ERROR };
    const key = cellKey(sheetId, row, col);
    const cached = cache.get(key);
    if (cached) return cached;

    const raw = sheet.cells.get(keyOf(row, col)) ?? null;
    if (!isFormula(raw)) {
      const result: CellResult = { value: raw, error: null };
      cache.set(key, result);
      return result;
    }

    // Re-entering a cell already on the evaluation stack is a cycle. Don't
    // cache here — the top frame for this key computes the real result.
    if (visiting.has(key)) return { value: null, error: CYCLE_ERROR };

    visiting.add(key);
    // All three are saved and restored rather than assigned, because
    // evaluating a reference re-enters this function mid-parse of the outer
    // formula: it needs its own parser and its own sheet, and the outer
    // parse needs both of its own back when the inner one returns.
    const outerSheetId = currentSheetId;
    const outerResolver = activeResolver;
    currentSheetId = sheetId;
    activeResolver = resolve;
    const parser = parserForDepth(parseDepth);
    parseDepth++;
    let result: CellResult;
    try {
      // Positions are 1-based, and ``sheet`` is what an unqualified
      // reference inside this formula resolves against — the sheet the
      // formula itself lives on, not the one the user is looking at.
      const parsed = parser.parse(raw.slice(1), {
        row: row + 1,
        col: col + 1,
        sheet: sheet.name,
      });
      result = toCellResult(parsed);
    } catch (e) {
      result = { value: null, error: errorToken(e) };
    } finally {
      parseDepth--;
      currentSheetId = outerSheetId;
      activeResolver = outerResolver;
      visiting.delete(key);
    }

    cache.set(key, result);
    return result;
  }

  return { evaluate };
};

/** Map a thrown parse error to an Excel-style token. The library raises a
 *  generic ``#ERROR!`` for an unimplemented/unknown function; surface that
 *  as ``#NAME?`` to match Excel and read better in the grid. */
const errorToken = (e: unknown): string => {
  if (e instanceof FormulaError) {
    if (/is not implemented/i.test(e.message)) return "#NAME?";
    return e.name;
  }
  return GENERIC_ERROR;
};

/** Normalize whatever ``parser.parse`` returns into a {@link CellResult}. */
const toCellResult = (parsed: unknown): CellResult => {
  if (parsed instanceof FormulaError) return { value: null, error: parsed.name };
  // A range/array result used where a scalar is expected: take the
  // top-left, matching Excel's implicit intersection well enough for v1.
  if (Array.isArray(parsed)) return toCellResult(parsed[0]?.[0] ?? null);
  if (isScalar(parsed)) return { value: parsed, error: null };
  return { value: null, error: "#VALUE!" };
};
