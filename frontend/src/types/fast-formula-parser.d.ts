/**
 * Minimal ambient declarations for ``fast-formula-parser`` (v1.x).
 *
 * The package ships no bundled types and there is no ``@types`` package,
 * so we declare just the surface the spreadsheet evaluator uses. The
 * runtime module does ``module.exports = FormulaParser`` and attaches
 * ``FormulaError`` (and others) as static properties; under the bundler's
 * CJS interop those become the default export and named exports.
 */
declare module "fast-formula-parser" {
  /** A formula error value (e.g. ``#DIV/0!``). ``name`` is the error code. */
  export class FormulaError extends Error {
    constructor(error: string, msg?: string, details?: unknown);
    readonly error: string;
    readonly name: string;
    /** Singletons for the standard error values, thrown or returned by a
     *  function to produce that error in the cell. */
    static readonly NAME: FormulaError;
    static readonly VALUE: FormulaError;
    static readonly NUM: FormulaError;
    static readonly NA: FormulaError;
    static readonly DIV0: FormulaError;
    static readonly REF: FormulaError;
  }

  export interface CellRef {
    sheet?: string;
    row: number; // 1-based
    col: number; // 1-based
  }

  export interface RangeRef {
    sheet?: string;
    from: { row: number; col: number }; // 1-based
    to: { row: number; col: number }; // 1-based
  }

  export interface FormulaParserConfig {
    onCell?: (ref: CellRef) => unknown;
    onRange?: (ref: RangeRef) => unknown[][];
    onVariable?: (name: string, sheet?: string) => unknown;
    functions?: Record<string, (...args: unknown[]) => unknown>;
    functionsNeedContext?: Record<string, (...args: unknown[]) => unknown>;
  }

  /** Info passed to a {@link FlattenHook} for each flattened parameter. */
  export interface FlattenInfo {
    isLiteral: boolean;
    isCellRef: boolean;
    isRangeRef: boolean;
    isArray: boolean;
    isUnion: boolean;
  }
  export type FlattenHook = (item: unknown, info: FlattenInfo) => void;

  /** Subset of the helper bag custom functions use to consume their args. */
  export interface FormulaHelpersType {
    flattenParams(
      params: unknown[],
      valueType: number | null,
      allowUnion: boolean,
      hook: FlattenHook,
      defValue?: unknown,
      minSize?: number
    ): void;
    /** Unwrap one argument to ``type``, applying Excel's coercion rules.
     *  Throws a {@link FormulaError} when the value can't be coerced.
     *  ``defValue`` makes the argument optional. */
    accept(param: unknown, type?: number | null, defValue?: unknown): unknown;
  }

  /** Argument-type enum (NUMBER, ARRAY, BOOLEAN, …). */
  export const Types: Record<string, number>;
  export const FormulaHelpers: FormulaHelpersType;

  export interface Position {
    row: number; // 1-based
    col: number; // 1-based
    sheet?: string;
  }

  export default class FormulaParser {
    constructor(config?: FormulaParserConfig);
    /** Parse a formula *without* the leading ``=``. Returns the value or a
     *  {@link FormulaError}; may also throw a FormulaError on bad syntax. */
    parse(inputText: string, position: Position, allowReturnArray?: boolean): unknown;
    parseAsync(inputText: string, position: Position, allowReturnArray?: boolean): Promise<unknown>;
    supportedFunctions(): string[];
  }
}
