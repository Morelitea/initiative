/**
 * A project's views — the shared, named, ordered ways its tasks are shown, each
 * a layout with fixed filters — as opposed to the filters one person keeps on
 * top of a view, which {@link useProjectTaskView} remembers.
 *
 * The set carries `can_configure`, computed server-side (the project's owner,
 * the initiative's managers, a community admin). Permission is never derived
 * client-side, and this is the one request that answers it for the tasks page
 * and the settings tab alike.
 */

import { useQuery } from "@tanstack/react-query";

import {
  type GetViewsParams,
  Tool,
  type ToolViewSetRead,
  type ToolViewSetWrite,
  type ToolViewWrite,
} from "@/api/generated/initiativeAPI.schemas";
import { getGetViewsQueryKey, getViews, putViews } from "@/api/generated/views/views";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useOptimisticMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

const target = (projectId: number): GetViewsParams => ({ tool: Tool.project, tool_id: projectId });

export const projectViewsQuery = (communityId: number, projectId: number) => ({
  queryKey: getGetViewsQueryKey(communityId, target(projectId)),
  queryFn: () => getViews(communityId, target(projectId)),
});

export const useProjectViews = (projectId: number | null) => {
  const communityId = useActiveCommunityId();
  return useQuery<ToolViewSetRead>({
    ...projectViewsQuery(communityId, projectId ?? 0),
    enabled: projectId !== null && Number.isFinite(projectId),
    // The client keeps previous data by default, which across a project switch
    // would show the last project's views — and its `can_configure`, which
    // gates the curation controls. Showing one project's permissions while
    // another loads is not a stale list, it is the wrong answer.
    placeholderData: undefined,
  });
};

/** Replace the project's whole set. The first save stores the shipped views
 *  with the change in it, since they are what `views` was read from. */
export const usePutProjectViews = (
  projectId: number,
  options?: MutationOpts<ToolViewSetRead, ToolViewSetWrite>
) =>
  useOptimisticMutation<ToolViewSetRead, ToolViewSetRead, ToolViewSetWrite>(
    {
      queryKey: (communityId) => getGetViewsQueryKey(communityId, target(projectId)),
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
      mutationFn: (communityId, data) => putViews(communityId, data, target(projectId)),
      errorKey: "projects:views.saveError",
    },
    options
  );

/** `set` to save with its views replaced by `views`, in order, keeping its
 *  item layouts. */
export const viewSetWrite = (set: ToolViewSetRead, views: ToolViewWrite[]): ToolViewSetWrite => ({
  views,
  item_layouts: set.item_layouts.map(({ item_kind, definition }) => ({ item_kind, definition })),
});

/** `set`'s views as a save takes them, to change and pass to {@link viewSetWrite}. */
export const viewWrites = (set: ToolViewSetRead): ToolViewWrite[] =>
  set.views.map(({ name, slug, is_default, definition }) => ({
    name,
    slug,
    is_default,
    definition,
  }));
