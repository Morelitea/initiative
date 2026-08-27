/**
 * Resolving what a list view is actually showing, from three sources.
 *
 * A saved preset is shared and named; the filter values someone last had are
 * personal and remembered. Both are real, and they are ranked rather than
 * merged:
 *
 *   1. the URL      — `?preset=` / `?view=`, so a link means the same thing
 *                     for whoever opens it
 *   2. the person   — their stored filters for this view, so coming back finds
 *                     it as they left it
 *   3. the project  — its default preset and default view, for a first visit
 *   4. a fallback   — everything, in the tool's first view
 *
 * A bare URL is deliberately never rewritten to name what it resolved to: it
 * has to keep meaning "whatever this project's default is *now*", so that
 * changing the default changes what the link shows. Naming a preset is what
 * `?preset=` is for, and the preset menu offers a Copy link that writes one.
 *
 * Tool-agnostic: the spec type and its equality are passed in.
 */

import { parsePresetSlug, parseViewMode } from "@/lib/filters/viewSearch";

export interface PresetLike<S> {
  slug: string;
  is_default: boolean;
  filters: S;
}

export interface PresetResolution<S, V extends string> {
  /** The filter values the list should apply. */
  spec: S;
  viewMode: V;
  /** The preset being shown, or null when the filters are ad hoc. */
  activeSlug: string | null;
  /** A preset is active but the filters have been tweaked away from it. */
  modified: boolean;
  /** `?preset=` named something this project does not have (deleted, renamed,
   *  or pasted from another project). The caller says so and carries on. */
  unresolvedPreset: boolean;
}

export interface ResolvePresetArgs<S, V extends string> {
  search: Record<string, unknown>;
  presets: readonly PresetLike<S>[];
  /** The viewer's remembered state for this view, if any. */
  stored?: { spec: S; viewMode?: V | null; activePresetSlug?: string | null } | null;
  allowedViews: readonly V[];
  /** The project's configured default view. */
  defaultView?: string | null;
  fallbackView: V;
  emptySpec: S;
  equals: (a: S, b: S) => boolean;
}

export function resolvePresetState<S, V extends string>({
  search,
  presets,
  stored,
  allowedViews,
  defaultView,
  fallbackView,
  emptySpec,
  equals,
}: ResolvePresetArgs<S, V>): PresetResolution<S, V> {
  const urlSlug = parsePresetSlug(search.preset);
  const urlView = parseViewMode(search.view, allowedViews);

  const bySlug = (slug: string | null | undefined) =>
    slug ? (presets.find((preset) => preset.slug === slug) ?? null) : null;

  const urlPreset = bySlug(urlSlug);
  // Only "unresolved" once the presets have actually loaded — an empty list
  // mid-fetch is not the same as a preset that does not exist.
  const unresolvedPreset = Boolean(urlSlug) && presets.length > 0 && urlPreset === null;

  const projectDefault = presets.find((preset) => preset.is_default) ?? null;

  let spec: S;
  let activeSlug: string | null;
  if (urlPreset) {
    spec = urlPreset.filters;
    activeSlug = urlPreset.slug;
  } else if (stored) {
    spec = stored.spec;
    activeSlug = bySlug(stored.activePresetSlug)?.slug ?? null;
  } else if (projectDefault) {
    spec = projectDefault.filters;
    activeSlug = projectDefault.slug;
  } else {
    spec = emptySpec;
    activeSlug = null;
  }

  // The chip says "modified" by comparing values, not by trusting the
  // remembered slug — the preset may have been edited since.
  const active = bySlug(activeSlug);
  const modified = active !== null && !equals(spec, active.filters);

  const viewMode =
    urlView ??
    (stored?.viewMode && allowedViews.includes(stored.viewMode) ? stored.viewMode : undefined) ??
    parseViewMode(defaultView, allowedViews) ??
    fallbackView;

  return { spec, viewMode, activeSlug, modified, unresolvedPreset };
}
