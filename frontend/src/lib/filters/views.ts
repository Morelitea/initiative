/**
 * Resolving what a list is showing: which of its views, and whose filters.
 *
 * A view is shared and named, and fixes a layout and filters. The filters one
 * person sets on top of a view are their own, remembered per view. Which view
 * is ranked:
 *
 *   1. the URL      — `?view=`, so a link opens the same view for whoever
 *                     opens it (and a link from before views, by the
 *                     layout or preset it named)
 *   2. the person   — the view they were last in
 *   3. the list     — its default view
 *
 * A view the URL names shows its own filters, so a link means the same thing
 * for whoever opens it. Otherwise the filters are this person's own for that
 * view, or the view's when they have none: coming back finds a view as they
 * left it, and their filters for one view never follow them into another.
 *
 * A bare URL is deliberately never rewritten to name what it resolved to: it
 * has to keep meaning "whatever the default is *now*", so that changing the
 * default changes what the link shows.
 *
 * Tool-agnostic: the spec type and its equality are passed in.
 */

export interface ViewLike<S> {
  slug: string;
  is_default: boolean;
  /** The view's fixed filters. */
  filters: S;
  definition: { layout: { type: string } };
}

/** What one person keeps for a list: the view they were last in, and their own
 *  filters for each view they changed, by slug. */
export interface StoredViews<S> {
  view: string | null;
  filters: Record<string, S>;
}

export interface ViewResolution<S, W extends ViewLike<S>> {
  /** The view shown, or null while there are none to show. */
  view: W | null;
  /** The filter values the list should apply. */
  spec: S;
  /** This person's own filters differ from the view's. */
  modified: boolean;
  /** The URL named a view this list does not have (deleted, renamed, or pasted
   *  from another list). The caller says so and carries on. */
  unresolvedView: boolean;
}

/** The layouts `?view=` named before a list had views, by the value it
 *  carried. Such a link meant the layout, so it opens the layout's view. */
const LEGACY_LAYOUTS: Partial<Record<string, string>> = {
  table: "table",
  kanban: "board",
  calendar: "calendar",
};

export interface ViewSearch {
  /** `view` from the URL. */
  view?: string;
  /** `preset` from a link made before views: `all` was the list as it is,
   *  and any other preset became the view with its slug. */
  preset?: string;
}

interface ViewMatch<S> {
  emptySpec: S;
  equals: (a: S, b: S) => boolean;
}

/** The view a URL names, or null. A link from before views that named a
 *  layout opens the first view of that layout with no filters, and the view
 *  with that slug only when there is none. */
export function viewNamedBy<S, W extends ViewLike<S>>(
  search: ViewSearch,
  views: readonly W[],
  { emptySpec, equals }: ViewMatch<S>
): W | null {
  const bySlug = (slug: string) => views.find((view) => view.slug === slug) ?? null;
  if (search.preset !== undefined) {
    return search.preset === "all"
      ? (views.find((view) => view.is_default) ?? views[0] ?? null)
      : bySlug(search.preset);
  }
  if (search.view === undefined) return null;
  const layout = LEGACY_LAYOUTS[search.view];
  const plain = layout
    ? views.find(
        (view) => view.definition.layout.type === layout && equals(view.filters, emptySpec)
      )
    : undefined;
  return plain ?? bySlug(search.view);
}

/** What `?view=` carries for `view`: its slug, or nothing when its slug
 *  would open another view (one holding a layout's old link). */
export function viewLink<S, W extends ViewLike<S>>(
  view: W,
  views: readonly W[],
  match: ViewMatch<S>
): string | undefined {
  return viewNamedBy({ view: view.slug }, views, match) === view ? view.slug : undefined;
}

export interface ResolveViewArgs<S, W extends ViewLike<S>> extends ViewMatch<S> {
  search: ViewSearch;
  views: readonly W[];
  stored?: StoredViews<S> | null;
}

export function resolveViewState<S, W extends ViewLike<S>>({
  search,
  views,
  stored,
  emptySpec,
  equals,
}: ResolveViewArgs<S, W>): ViewResolution<S, W> {
  const urlView = viewNamedBy(search, views, { emptySpec, equals });
  // Only "unresolved" once the views have actually loaded — an empty list
  // mid-fetch is not the same as a view that does not exist.
  const unresolvedView =
    (search.preset ?? search.view) !== undefined && views.length > 0 && urlView === null;

  const view =
    urlView ??
    views.find((each) => each.slug === stored?.view) ??
    views.find((each) => each.is_default) ??
    views[0] ??
    null;
  const base = view?.filters ?? emptySpec;
  const own =
    view && view !== urlView && stored && Object.hasOwn(stored.filters, view.slug)
      ? stored.filters[view.slug]
      : undefined;

  return {
    view,
    spec: own ?? base,
    modified: own !== undefined && !equals(own, base),
    unresolvedView,
  };
}
