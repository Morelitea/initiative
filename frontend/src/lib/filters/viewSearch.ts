/**
 * The two search params that make a list view linkable: which view it is in,
 * and which saved preset it is showing.
 *
 * Tool-agnostic on purpose — nothing here imports `Tool`. A tool adopting
 * presets passes its own view vocabulary in, because that vocabulary genuinely
 * differs per tool (tasks are table/kanban/calendar, a counter group is
 * row/grid, a calendar is day/week/month/...) and a shared enum would be wrong
 * at the type level. Everything else about presets is the same everywhere, so
 * it is shared rather than declared per tool.
 */

/** Slugs are lowercase kebab, matching what the API derives from a name. */
const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const MAX_SLUG_LENGTH = 64;

export interface ViewSearch<V extends string> {
  /** Which view the list is in. Absent means "whatever the default resolves to". */
  view?: V;
  /** Which saved preset the list is showing, by slug. */
  preset?: string;
}

/** Coerce a `?preset=` value. Anything malformed is dropped, never thrown —
 *  a pasted link with a typo should still render the project. */
export function parsePresetSlug(raw: unknown): string | undefined {
  if (typeof raw !== "string") return undefined;
  if (raw.length === 0 || raw.length > MAX_SLUG_LENGTH) return undefined;
  return SLUG_PATTERN.test(raw) ? raw : undefined;
}

/** Coerce a `?view=` value against the tool's own vocabulary. */
export function parseViewMode<V extends string>(
  raw: unknown,
  allowed: readonly V[]
): V | undefined {
  if (typeof raw !== "string") return undefined;
  return (allowed as readonly string[]).includes(raw) ? (raw as V) : undefined;
}

export function parseViewSearch<V extends string>(
  search: Record<string, unknown>,
  allowed: readonly V[]
): ViewSearch<V> {
  return {
    view: parseViewMode(search.view, allowed),
    preset: parsePresetSlug(search.preset),
  };
}
