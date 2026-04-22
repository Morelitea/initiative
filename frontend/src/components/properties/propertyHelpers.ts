import {
  PropertyType,
  type PropertyDefinitionRead,
  type PropertyOption,
  type PropertySummary,
} from "@/api/generated/initiativeAPI.schemas";

/**
 * Slugify a user-entered label into a stable option value slug. Output is
 * lowercase, alphanumeric plus `_` and `-`, trimmed of leading/trailing
 * underscores, and capped at 64 chars. Used both when creating a whole
 * definition (AddPropertyButton) and when appending a single option inline
 * (PropertyInput).
 */
export const slugify = (raw: string): string =>
  raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 64);

export const typeRequiresOptions = (type: PropertyType): boolean =>
  type === PropertyType.select || type === PropertyType.multi_select;

export const isEmptyPropertyValue = (value: unknown): boolean => {
  if (value === null || value === undefined) return true;
  if (typeof value === "string" && value.trim() === "") return true;
  if (Array.isArray(value) && value.length === 0) return true;
  return false;
};

/**
 * Build a fresh, unique option slug for a label that's about to be appended
 * to a definition's options array. If the straight-slugified value is already
 * in use, append ``-2``, ``-3``, … until we find a free slot. The caller is
 * expected to have already rejected duplicate labels (case-insensitive).
 */
export const buildUniqueOptionSlug = (label: string, existing: PropertyOption[]): string => {
  const base = slugify(label) || "option";
  const used = new Set(existing.map((o) => o.value));
  if (!used.has(base)) return base;
  for (let i = 2; i < 1000; i += 1) {
    const candidate = `${base}-${i}`;
    if (!used.has(candidate)) return candidate;
  }
  // Extremely unlikely; fall back to a timestamp suffix.
  return `${base}-${Date.now()}`;
};

export const findOptionByLabel = (
  definition: PropertyDefinitionRead,
  label: string
): PropertyOption | undefined => {
  const needle = label.trim().toLowerCase();
  if (!needle) return undefined;
  return (definition.options ?? []).find((option) => option.label.trim().toLowerCase() === needle);
};

/**
 * Extract the list of a summary's "attached and non-empty" entries, in the
 * same order they were returned by the server. Used by card chip rows so
 * empty rows are omitted.
 */
export const nonEmptyPropertySummaries = (
  summaries: PropertySummary[] | undefined | null
): PropertySummary[] => {
  if (!summaries) return [];
  return summaries.filter((summary) => !isEmptyPropertyValue(summary.value));
};
