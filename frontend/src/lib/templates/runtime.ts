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
  isCelError,
  isCelList,
  isCelMap,
  parse,
  plan,
} from "@bufbuild/cel";
import { strings } from "@bufbuild/cel/ext";
import i18n from "i18next";

import { formatDate, formatDateTime } from "@/lib/formatDate";

const number = (value: number | bigint) =>
  new Intl.NumberFormat(i18n.language).format(typeof value === "bigint" ? Number(value) : value);

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

export function evaluate(source: string, bindings: Record<string, unknown>): unknown {
  return toPlain(program(source)(bindings));
}
