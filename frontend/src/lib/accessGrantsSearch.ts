/**
 * What the Access tab can be opened with: one community already chosen in one
 * of its forms. The Communities tab links here from a row, so the community
 * arrives picked rather than typed, and the form it was meant for says which
 * of the two picks it up.
 */

export type AccessGrantsForm = "request" | "break_glass";

export interface AccessGrantsSearch {
  /** The community the form starts with. */
  community?: number;
  /** Its name, carried along so the picker can show it without a lookup. */
  name?: string;
  /** Which form it is for. */
  form?: AccessGrantsForm;
}

export const validateAccessGrantsSearch = (search: Record<string, unknown>): AccessGrantsSearch => {
  const community = Number(search.community);
  if (!Number.isInteger(community) || community <= 0) return {};
  const form = search.form === "request" || search.form === "break_glass" ? search.form : undefined;
  const name = typeof search.name === "string" && search.name.trim() ? search.name : undefined;
  return { community, ...(name ? { name } : {}), ...(form ? { form } : {}) };
};
