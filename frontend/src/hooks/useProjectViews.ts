/**
 * A tool's views — a project's own, or the initiative's calendar page's — and
 * the item pages laid out beside them. A project's views are the shared,
 * named, ordered ways its tasks are shown, each a layout with fixed filters —
 * as opposed to the filters one person keeps on top of a view, which
 * {@link useProjectTaskView} remembers.
 *
 * The set carries `can_configure`, computed server-side (for a project, its
 * owner, the initiative's managers and a community admin; for the calendar
 * page, the initiative's managers and a community admin). Permission is never derived
 * client-side, and this is the one request that answers it for the tasks page
 * and the settings tab alike.
 */

import { useQuery } from "@tanstack/react-query";

import {
  type GetViewsParams,
  type ItemLayoutDefinitionInput,
  Tool,
  type ToolItemLayoutWrite,
  type ToolViewSetRead,
  type ToolViewSetWrite,
  type ToolViewWrite,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getGetInitiativeViewsQueryKey,
  getGetViewsQueryKey,
  getInitiativeViews,
  getViews,
  putViews,
} from "@/api/generated/views/views";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useOptimisticMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

/** A project's views, which are its own. */
export const projectTarget = (projectId: number): GetViewsParams => ({
  tool: Tool.project,
  tool_id: projectId,
});

/** The initiative's calendar page, whose views and event page every calendar
 *  in it shares. */
export const calendarTarget = (initiativeId: number): GetViewsParams => ({
  tool: Tool.calendar,
  initiative_id: initiativeId,
});

export const toolViewsQuery = (communityId: number, target: GetViewsParams) => ({
  queryKey: getGetViewsQueryKey(communityId, target),
  queryFn: () => getViews(communityId, target),
});

/** A target's set, or nothing while `target` is null. */
export const useToolViews = (target: GetViewsParams | null) => {
  const communityId = useActiveCommunityId();
  return useQuery<ToolViewSetRead>({
    ...toolViewsQuery(communityId, target ?? projectTarget(0)),
    enabled: target !== null,
    // The client keeps previous data by default, which across a target switch
    // would show the last target's views — and its `can_configure`, which
    // gates the curation controls. Showing one target's permissions while
    // another loads is not a stale list, it is the wrong answer.
    placeholderData: undefined,
  });
};

export const useProjectViews = (projectId: number | null) =>
  useToolViews(projectId !== null && Number.isFinite(projectId) ? projectTarget(projectId) : null);

/** Every project's views in an initiative the reader can open, for its
 *  settings, with whether the reader may change each. */
export const useInitiativeViews = (initiativeId: number) => {
  const communityId = useActiveCommunityId();
  const params = { initiative_id: initiativeId };
  return useQuery({
    queryKey: getGetInitiativeViewsQueryKey(communityId, params),
    queryFn: () => getInitiativeViews(communityId, params),
    // Another initiative's projects, while this one's load, would be listed
    // under this one's addresses.
    placeholderData: undefined,
  });
};

/** Replace a target's whole set. The first save stores the shipped views
 *  with the change in it, since they are what `views` was read from. */
export const usePutToolViews = (
  target: GetViewsParams,
  options?: MutationOpts<ToolViewSetRead, ToolViewSetWrite>
) =>
  useOptimisticMutation<ToolViewSetRead, ToolViewSetRead, ToolViewSetWrite>(
    {
      queryKey: (communityId) => getGetViewsQueryKey(communityId, target),
      // A view saved for the first time has no slug until the server names it,
      // so it appears with the answer.
      apply: (set, write) => ({
        ...set,
        stored: true,
        views: write.views.flatMap(({ slug, name, is_default = false, definition }, position) =>
          slug
            ? [
                {
                  id: set.views.find((view) => view.slug === slug)?.id ?? null,
                  slug,
                  name,
                  position,
                  is_default,
                  definition,
                },
              ]
            : []
        ),
      }),
      seed: (_, set) => set,
      // The set itself is the answer; the initiative's list of sets reads anew.
      invalidate: () => invalidate(q.initiativeViews()),
      mutationFn: (communityId, data) => putViews(communityId, data, target),
      errorKey: "projects:views.saveError",
    },
    options
  );

/** The layout of a kind of item's page, or null where it draws the shipped page. */
export const itemLayoutOf = (
  set: ToolViewSetRead | undefined,
  itemKind: ToolItemLayoutWrite["item_kind"]
): ItemLayoutDefinitionInput | null =>
  (set?.item_layouts.find((layout) => layout.item_kind === itemKind)?.definition as
    | ItemLayoutDefinitionInput
    | undefined) ?? null;

/** `set` to save with its views replaced by `views`, in order, and its item
 *  pages by `layouts` where given. */
export const viewSetWrite = (
  set: ToolViewSetRead,
  views: ToolViewWrite[],
  layouts: ToolItemLayoutWrite[] = set.item_layouts.map(({ item_kind, definition }) => ({
    item_kind,
    definition: definition as ItemLayoutDefinitionInput,
  }))
): ToolViewSetWrite => ({ views, item_layouts: layouts });

/** `set`'s views as a save takes them, to change and pass to {@link viewSetWrite}. */
export const viewWrites = (set: ToolViewSetRead): ToolViewWrite[] =>
  set.views.map(({ name, slug, is_default, definition }) => ({
    name,
    slug,
    is_default,
    definition,
  }));
