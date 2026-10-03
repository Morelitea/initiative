/**
 * The community directory's shelves.
 *
 * Derived from the generated `CommunityCategory` enum rather than restated, so a
 * category added server-side reaches the filter rail and the settings picker
 * without an edit here — and in the order the backend declares, which is also
 * the order it stores a guild's selection in.
 *
 * Labels are looked up per category key in the `guilds` namespace, so a new
 * category shows its own key until it is translated rather than silently
 * rendering as another one's name.
 */

import type { TFunction } from "i18next";

import { CommunityCategory } from "@/api/generated/initiativeAPI.schemas";

export const GUILD_CATEGORIES: CommunityCategory[] = Object.values(CommunityCategory);

/** The namespaces every surface that draws a category label already loads. */
export type GuildCategoryT = TFunction<readonly ["guilds", "common"]>;

export const guildCategoryLabel = (category: CommunityCategory, t: GuildCategoryT): string =>
  // The default is the key itself: a category this build has no label for
  // yet should read as something rather than as nothing.
  t(`guilds:community.categories.${category}`, { defaultValue: category });

/** Narrow an unvalidated value (a URL search param) to a category, or nothing. */
export const asGuildCategory = (value: unknown): CommunityCategory | undefined =>
  GUILD_CATEGORIES.includes(value as CommunityCategory) ? (value as CommunityCategory) : undefined;

/** Narrow an unvalidated value (one category, or a list of them) to the
 *  categories it names, each once and in the order given. */
export const asGuildCategories = (value: unknown): CommunityCategory[] => {
  const given = Array.isArray(value) ? value : [value];
  return given.filter(
    (item, index): item is CommunityCategory =>
      asGuildCategory(item) !== undefined && given.indexOf(item) === index
  );
};
