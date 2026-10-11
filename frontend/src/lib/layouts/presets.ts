/**
 * A list layout's presets: filters, and for a table a sort, that a person
 * picks to start from. Picking one makes them that person's own; the preset
 * itself stays as the layout keeps it.
 */

import type { SortingState } from "@tanstack/react-table";

import type {
  LayoutPreset,
  ListLayoutDefinitionInput,
  TaskFilterSpec as PresetFilters,
  PresetSortField,
  SortDir,
} from "@/api/generated/initiativeAPI.schemas";
import {
  ASSIGNEE_ME,
  ASSIGNEE_NONE,
  type StoredTaskFilters,
  specFromStored,
  type TaskFilterSpec,
  tableSortFields,
  taskTableSorting,
} from "@/lib/filters/taskFilters";
import { slugify } from "@/lib/slug";

/** A preset as a list offers it. A shipped one is named by `nameKey`, in the
 *  reader's words. */
export type Preset = {
  slug: string;
  name: string;
  nameKey?: string;
  spec: TaskFilterSpec;
  sorting: SortingState;
};

/** What a project's lists offer until one is changed, each named in
 *  `projects`. */
const SHIPPED: readonly { slug: string; nameKey: string; filters: StoredTaskFilters }[] = [
  {
    slug: "incomplete",
    nameKey: "presets.incomplete",
    filters: { status_categories: ["backlog", "todo", "in_progress"] },
  },
  { slug: "unassigned", nameKey: "presets.unassigned", filters: { assignees: [ASSIGNEE_NONE] } },
  { slug: "mine", nameKey: "presets.mine", filters: { assignees: [ASSIGNEE_ME] } },
];

/** How many presets a list may offer, as the server allows. */
export const MAX_PRESETS = 20;

/** A shipped preset's name, by its slug. */
const SHIPPED_NAMES = new Map(SHIPPED.map(({ slug, nameKey }) => [slug, nameKey]));

/** The presets a list offers: its own, or the shipped ones where it keeps
 *  none of its own. One kept with no name is a shipped one no one renamed,
 *  named in each reader's words. */
export const presetsOf = (definition: ListLayoutDefinitionInput | undefined): Preset[] =>
  definition?.presets == null
    ? SHIPPED.map(({ slug, nameKey, filters }) => ({
        slug,
        name: "",
        nameKey,
        spec: specFromStored(filters),
        sorting: [],
      }))
    : definition.presets.map((preset) => ({
        slug: preset.slug,
        name: preset.name ?? preset.slug,
        nameKey: preset.name ? undefined : SHIPPED_NAMES.get(preset.slug),
        spec: specFromStored(preset.filters as StoredTaskFilters),
        sorting: taskTableSorting(preset.sort ?? []),
      }));

/** A preset's name, in the reader's words where it is shipped. */
export const presetName = (preset: Preset, t: (key: string) => string): string =>
  preset.nameKey ? t(preset.nameKey) : preset.name;

/** `preset` as a layout keeps it: a shipped one by its slug alone, so each
 *  reader still reads its name in their own words. */
export const storedPreset = (preset: Preset): LayoutPreset => ({
  ...(preset.nameKey ? {} : { name: preset.name }),
  slug: preset.slug,
  filters: preset.spec as unknown as PresetFilters,
  sort: tableSortFields(preset.sorting).map(({ field, dir }) => ({
    field: field as PresetSortField,
    dir: dir as SortDir,
  })),
});

const MAX_SLUG_LENGTH = 64;

/** A slug for a new preset named `name`, none of `taken`: what a link to it
 *  carries, so it stays when the preset is renamed. */
export const presetSlug = (name: string, taken: readonly string[]): string => {
  const base =
    slugify(name)
      .replaceAll("_", "-")
      .split("-")
      .filter(Boolean)
      .join("-")
      .slice(0, MAX_SLUG_LENGTH - 4)
      .replace(/-$/, "") || "preset";
  let slug = base;
  for (let n = 2; taken.includes(slug); n += 1) slug = `${base}-${n}`;
  return slug;
};
