/**
 * The search params that name one of a target's layouts: `?layout=` on a list,
 * which of its list layouts it shows, and on the layout editor, which layout
 * it opens on.
 */

import { type DetailLayoutRead, ListLayoutReadKind } from "@/api/generated/initiativeAPI.schemas";

const LISTS: readonly string[] = Object.values(ListLayoutReadKind);
/** The details a target can lay out. */
const DETAILS: readonly DetailLayoutRead["kind"][] = ["task"];
const KINDS: readonly string[] = [...LISTS, ...DETAILS];

/** Coerce a list's `?layout=`. Anything else is dropped, never thrown — a
 *  pasted link with a typo should still render the list. */
export const parseListLayout = (raw: unknown): ListLayoutReadKind | undefined =>
  typeof raw === "string" && LISTS.includes(raw) ? (raw as ListLayoutReadKind) : undefined;

/** Coerce the layout editor's `?layout=`, which may also name a detail. */
export const parseLayoutKind = (raw: unknown): string | undefined =>
  typeof raw === "string" && KINDS.includes(raw) ? raw : undefined;
