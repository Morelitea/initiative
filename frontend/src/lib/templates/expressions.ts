/**
 * Check a template's CEL expressions before anything evaluates them.
 *
 * CEL cannot loop, but `@bufbuild/cel` has no cost estimator and no public type
 * checker, so the bounds are ours, read off the syntax tree:
 *
 * - comprehensions (`map`, `filter`, `all`, `exists`, `exists_one`) nest at
 *   most two deep: n items at depth d is n to the power d steps;
 * - an expression has a length and a node count it may not pass;
 * - every name is one the template was given, every field one its data has,
 *   and every function one on the list below.
 *
 * A template that breaks one does not compile, so a theme that would slow every
 * member's board never saves.
 */

import { parse } from "@bufbuild/cel";

import { fieldShape, itemShape, resolveShape, type Shape } from "./shapes.ts";

export const MAX_EXPRESSION_LENGTH = 400;
export const MAX_EXPRESSION_NODES = 200;
export const MAX_COMPREHENSION_DEPTH = 2;

/** The operators, as CEL's parser names them, and the macros' own helpers. */
const OPERATORS = new Set([
  "_&&_",
  "_||_",
  "_==_",
  "_!=_",
  "_<_",
  "_<=_",
  "_>_",
  "_>=_",
  "_+_",
  "_-_",
  "_*_",
  "_/_",
  "_%_",
  "!_",
  "-_",
  "_?_:_",
  "_[_]",
  "@in",
  "@not_strictly_false",
]);

/** CEL's standard functions a template may call. */
const STANDARD_FUNCTIONS = [
  "size",
  "contains",
  "startsWith",
  "endsWith",
  "matches",
  "int",
  "uint",
  "double",
  "string",
  "bool",
  "type",
  "dyn",
  "timestamp",
  "duration",
  "getFullYear",
  "getMonth",
  "getDate",
  "getDayOfMonth",
  "getDayOfWeek",
  "getDayOfYear",
  "getHours",
  "getMinutes",
  "getSeconds",
  "getMilliseconds",
];

/** The `strings` extension, as `@bufbuild/cel/ext` ships it. */
const STRING_FUNCTIONS = [
  "charAt",
  "format",
  "indexOf",
  "join",
  "lastIndexOf",
  "lowerAscii",
  "replace",
  "split",
  "substring",
  "trim",
  "upperAscii",
];

/** Ours, defined in runtime.ts: text a member reads in their own language. */
export const DISPLAY_FUNCTIONS = ["format_date", "format_number", "t"] as const;

const FUNCTIONS = new Set<string>([
  ...STANDARD_FUNCTIONS,
  ...STRING_FUNCTIONS,
  ...DISPLAY_FUNCTIONS,
]);

/** The names an expression may read, and what each holds. */
export type ExpressionScope = ReadonlyMap<string, Shape>;

/** Why an expression was refused, in words for whoever wrote it. */
export type ExpressionProblem = string;

export interface ExpressionCheck {
  problems: ExpressionProblem[];
  /** What the expression yields, as far as the walk can tell. */
  shape: Shape;
}

// The parser's tree, read structurally: only the fields this walk uses.
interface CelNode {
  id: bigint;
  exprKind: {
    case?: string;
    value?: unknown;
  };
}
interface CelSelect {
  operand?: CelNode;
  field: string;
}
interface CelCall {
  target?: CelNode;
  function: string;
  args: CelNode[];
}
interface CelEntry {
  keyKind: { case?: string; value?: CelNode };
  value?: CelNode;
}
interface CelComprehension {
  iterVar: string;
  iterVar2: string;
  iterRange?: CelNode;
  accuVar: string;
  accuInit?: CelNode;
  loopCondition?: CelNode;
  loopStep?: CelNode;
  result?: CelNode;
}

/**
 * Every problem with `source` read against `scope`, or none.
 *
 * The walk returns what each part holds, so `task.priority` is checked against
 * the task, and a comprehension's variable holds one item of the list it walks.
 */
export function checkExpression(source: string, scope: ExpressionScope): ExpressionCheck {
  if (source.length > MAX_EXPRESSION_LENGTH) {
    return {
      problems: [`Expressions are at most ${MAX_EXPRESSION_LENGTH} characters long`],
      shape: "any",
    };
  }
  let root: CelNode;
  // Which macro each comprehension came from, by its node id: filter keeps the
  // list's items, map makes new ones, and all/exists answer yes or no.
  let macros: Record<string, CelNode>;
  try {
    const parsed = parse(source);
    root = parsed.expr as unknown as CelNode;
    macros = (parsed.sourceInfo?.macroCalls ?? {}) as unknown as Record<string, CelNode>;
  } catch (error) {
    return {
      problems: [`Does not parse: ${error instanceof Error ? error.message : String(error)}`],
      shape: "any",
    };
  }

  const problems: ExpressionProblem[] = [];
  let nodes = 0;

  const walk = (node: CelNode | undefined, names: ExpressionScope, depth: number): Shape => {
    if (!node) return "any";
    nodes++;
    const { case: kind, value } = node.exprKind;
    switch (kind) {
      case "identExpr": {
        const name = (value as { name: string }).name;
        const shape = names.get(name);
        if (shape === undefined) {
          problems.push(`Nothing is called ${name} here`);
          return "any";
        }
        return shape;
      }
      case "selectExpr": {
        const select = value as CelSelect;
        const operand = walk(select.operand, names, depth);
        const shape = fieldShape(operand, select.field);
        if (shape === undefined) {
          problems.push(`There is no field ${select.field} here`);
          return "any";
        }
        return shape;
      }
      case "callExpr": {
        const call = value as CelCall;
        if (!OPERATORS.has(call.function) && !FUNCTIONS.has(call.function)) {
          problems.push(`${call.function}() is not a function templates may use`);
        }
        walk(call.target, names, depth);
        const args = call.args.map((argument) => walk(argument, names, depth));
        if (call.function === "_[_]") {
          const indexed = resolveShape(args[0] ?? "any");
          if (typeof indexed === "object" && "list" in indexed) return indexed.list;
          if (typeof indexed === "object" && "map" in indexed) return indexed.map;
        }
        return "any";
      }
      case "comprehensionExpr": {
        const comprehension = value as CelComprehension;
        if (depth + 1 > MAX_COMPREHENSION_DEPTH) {
          problems.push(`map, filter, all and exists nest at most ${MAX_COMPREHENSION_DEPTH} deep`);
        }
        const range = walk(comprehension.iterRange, names, depth);
        const inner = new Map(names);
        inner.set(comprehension.iterVar, itemShape(range));
        if (comprehension.iterVar2) inner.set(comprehension.iterVar2, "any");
        inner.set(comprehension.accuVar, "any");
        walk(comprehension.accuInit, names, depth + 1);
        walk(comprehension.loopCondition, inner, depth + 1);
        walk(comprehension.loopStep, inner, depth + 1);
        walk(comprehension.result, inner, depth + 1);
        const macro = macros[String(node.id)]?.exprKind.value as CelCall | undefined;
        switch (macro?.function) {
          case "filter":
            return range;
          case "map":
            return { list: "any" };
          case "all":
          case "exists":
          case "exists_one":
            return "boolean";
          default:
            return "any";
        }
      }
      case "listExpr": {
        for (const element of (value as { elements: CelNode[] }).elements) {
          walk(element, names, depth);
        }
        return "any";
      }
      case "structExpr": {
        const entries = (value as { entries: CelEntry[] }).entries;
        for (const entry of entries) {
          if (entry.keyKind.case === "mapKey") walk(entry.keyKind.value, names, depth);
          walk(entry.value, names, depth);
        }
        return "any";
      }
      default:
        return "any";
    }
  };

  const shape = walk(root, scope, 0);
  if (nodes > MAX_EXPRESSION_NODES) {
    problems.push(`Expressions are at most ${MAX_EXPRESSION_NODES} parts`);
  }
  return { problems: [...new Set(problems)], shape };
}
