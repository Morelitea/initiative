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
  type ItemLayoutDefinitionInput,
  Tool,
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

/** Every project's views in an initiative the reader can open, for its
 *  settings, with whether the reader may change each. */
export const useInitiativeViews = (initiativeId: number) => {
  const communityId = useActiveCommunityId();
  const params = { initiative_id: initiativeId };
  return useQuery({
    queryKey: getGetInitiativeViewsQueryKey(communityId, params),
    queryFn: () => getInitiativeViews(communityId, params),
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
      // The set itself is the answer; the initiative's list of sets reads anew.
      invalidate: () => invalidate(q.initiativeViews()),
      mutationFn: (communityId, data) => putViews(communityId, data, target(projectId)),
      errorKey: "projects:views.saveError",
    },
    options
  );

/** The project's task page layout, or null where it draws the shipped page. */
export const taskPageOf = (set: ToolViewSetRead | undefined): ItemLayoutDefinitionInput | null =>
  (set?.item_layouts.find((layout) => layout.item_kind === "task")?.definition as
    | ItemLayoutDefinitionInput
    | undefined) ?? null;

/** `set` to save with its views replaced by `views`, in order, and its task
 *  page by `taskPage` where given (null: the shipped page). */
export const viewSetWrite = (
  set: ToolViewSetRead,
  views: ToolViewWrite[],
  taskPage: ItemLayoutDefinitionInput | null = taskPageOf(set)
): ToolViewSetWrite => ({
  views,
  item_layouts: taskPage ? [{ item_kind: "task", definition: taskPage }] : [],
});

/** `set`'s views as a save takes them, to change and pass to {@link viewSetWrite}. */
export const viewWrites = (set: ToolViewSetRead): ToolViewWrite[] =>
  set.views.map(({ name, slug, is_default, definition }) => ({
    name,
    slug,
    is_default,
    definition,
  }));
