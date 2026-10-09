/**
 * Evaluate a compiled template's expressions in the browser.
 *
 * Each expression was checked when its template compiled (expressions.ts). Here
 * it is planned once, cached by its source, and run against the section's data.
 * A runtime failure, such as a field the row does not have today, renders as
 * nothing rather than breaking the screen.
 */

import {
  CelScalar,
  type CelValue,
  celEnv,
  celFunc,
  celList,
  celMap,
  isCelError,
  isCelList,
  isCelMap,
  parse,
  plan,
} from "@bufbuild/cel";
import { strings } from "@bufbuild/cel/ext";
import i18n from "i18next";

import { formatDate, formatDateTime } from "@/lib/formatDate";
import { numberFormat } from "@/lib/intl";

const number = (value: number | bigint) =>
  numberFormat(i18n.language).format(typeof value === "bigint" ? Number(value) : value);

/** The display functions templates call (DISPLAY_FUNCTIONS in expressions.ts). */
const DISPLAY = [
  celFunc("format_date", [CelScalar.STRING], CelScalar.STRING, (value) => formatDate(value)),
  celFunc("format_date", [CelScalar.STRING, CelScalar.STRING], CelScalar.STRING, (value, style) =>
    style === "datetime" ? formatDateTime(value) : formatDate(value)
  ),
  celFunc("format_number", [CelScalar.DOUBLE], CelScalar.STRING, number),
  celFunc("format_number", [CelScalar.INT], CelScalar.STRING, number),
  // A template names its keys as text, so they are checked against the catalogue, not the types.
  celFunc("t", [CelScalar.STRING], CelScalar.STRING, (key) =>
    (i18n.t as (key: string) => string)(key)
  ),
];

const env = celEnv({ funcs: [...strings, ...DISPLAY] });

type Program = (bindings: Record<string, unknown>) => unknown;

const programs = new Map<string, Program>();

/** The planned program for `source`, planned once however often it renders. */
export function program(source: string): Program {
  let planned = programs.get(source);
  if (!planned) {
    const run = plan(env, parse(source));
    planned = (bindings) => run(bindings as never);
    programs.set(source, planned);
  }
  return planned;
}

/** A CEL result as plain JavaScript: lists as arrays, maps as objects, errors as undefined. */
export function toPlain(value: unknown): unknown {
  if (value === null || value === undefined) return value;
  if (isCelError(value)) return undefined;
  if (typeof value === "bigint") return Number(value);
  if (isCelList(value)) return Array.from(value as Iterable<CelValue>, toPlain);
  if (isCelMap(value)) {
    return Object.fromEntries(
      Array.from(value as Iterable<[unknown, CelValue]>, ([key, item]) => [
        String(key),
        toPlain(item),
      ])
    );
  }
  return value;
}

/** Each object CEL has read, as CEL reads it: the data a route passes does not change. */
const wrappedObjects = new WeakMap<object, unknown>();

const wrap = (value: unknown): unknown => {
  if (value === null || typeof value !== "object") return value;
  let wrapped = wrappedObjects.get(value);
  if (wrapped === undefined) {
    if (Array.isArray(value)) wrapped = celList(value);
    else if (value.constructor === Object) wrapped = celMap(new Map(Object.entries(value)));
    else return value;
    wrappedObjects.set(value, wrapped);
  }
  return wrapped;
};

/**
 * A section's data as CEL reads it. CEL wraps a plain object in a map each time
 * an expression reads it, so each object is wrapped once, for every expression
 * and every render that reads it.
 */
export function bindings(data: Record<string, unknown>): Record<string, unknown> {
  const wrapped: Record<string, unknown> = {};
  for (const [name, value] of Object.entries(data)) wrapped[name] = wrap(value);
  return wrapped;
}

export function evaluate(source: string, bindings: Record<string, unknown>): unknown {
  return toPlain(program(source)(bindings));
}
