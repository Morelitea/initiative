/**
 * A configured value in the type its app declared for it.
 *
 * Every control that fills an app endpoint's parameter reads a **string** — a
 * `<Select>` hands back its option's value, a text field hands back its text,
 * a multi-select hands back an array of option values. The declaration those
 * options came from may say the parameter is an `int`, and the proxy holds a
 * value to that declaration exactly: `_coerce_param` refuses a string where an
 * int was declared, and refuses it per *entry* for a parameter marked `list`.
 *
 * So without this the two halves disagree in a way nothing catches until the
 * tile is drawn: the form saves, the binding stores, and the fetch fails with
 * `INVALID_PARAMS` on a widget somebody has already finished configuring.
 *
 * Kept out of the dialog because it is a rule about a contract rather than
 * about a control, and because it is the kind of thing worth testing directly.
 */

import type { AppDataParam } from "@/api/appData";

/** The types a manifest may declare for a parameter that holds a number. */
const NUMERIC = new Set(["int", "number"]);

/**
 * One value, or `undefined` where the text is not one.
 *
 * `undefined` is how a control says "there is no answer here" — an emptied
 * field, or an entry that is not a value of the declared type. The caller drops
 * the key rather than sending something the endpoint would refuse.
 */
export function asDeclaredType(
  param: Pick<AppDataParam, "type">,
  raw: string
): string | number | boolean | undefined {
  const text = raw.trim();
  if (!text) return undefined;

  if (NUMERIC.has(param.type)) {
    const parsed = Number(text);
    if (!Number.isFinite(parsed)) return undefined;
    // `int` means an integer, and 1.5 is not one — the proxy refuses it, so
    // offering it here would only move the failure to the fetch.
    if (param.type === "int" && !Number.isInteger(parsed)) return undefined;
    return parsed;
  }

  if (param.type === "bool") {
    if (text === "true") return true;
    if (text === "false") return false;
    return undefined;
  }

  return text;
}

/**
 * Several of them, in declaration order, dropping any that is not a value.
 *
 * Each entry is held to the same type the single value would be, because that
 * is what the proxy does: `list` says how many, never what kind.
 */
export function asDeclaredList(
  param: Pick<AppDataParam, "type">,
  raw: readonly string[]
): (string | number | boolean)[] {
  const values: (string | number | boolean)[] = [];
  for (const entry of raw) {
    const value = asDeclaredType(param, entry);
    if (value !== undefined) values.push(value);
  }
  return values;
}

/** The text a control shows for a stored value, which is always a string. */
export const asControlValue = (value: unknown): string =>
  value === undefined || value === null ? "" : String(value);
