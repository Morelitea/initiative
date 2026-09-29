/**
 * A project's saved filter presets — the shared, named filter sets everyone in
 * the project sees, as opposed to the personal filter state
 * {@link useViewPreference} remembers.
 *
 * The list response carries `can_manage`, computed server-side (a project
 * manager, the project owner, or a guild admin). Permission is never derived
 * client-side, and this is the one request that answers it for the tasks page
 * and the settings tab alike.
 */

import { useQuery } from "@tanstack/react-query";

import {
  createFilterPresetApiV1CGuildIdProjectsProjectIdFilterPresetsPost,
  deleteFilterPresetApiV1CGuildIdProjectsProjectIdFilterPresetsPresetIdDelete,
  getListFilterPresetsApiV1CGuildIdProjectsProjectIdFilterPresetsGetQueryKey,
  listFilterPresetsApiV1CGuildIdProjectsProjectIdFilterPresetsGet,
  reorderFilterPresetsApiV1CGuildIdProjectsProjectIdFilterPresetsReorderPost,
  updateFilterPresetApiV1CGuildIdProjectsProjectIdFilterPresetsPresetIdPatch,
} from "@/api/generated/filter-presets/filter-presets";
import type {
  FilterPresetCreate,
  FilterPresetListResponse,
  FilterPresetRead,
  FilterPresetReorderRequest,
  FilterPresetUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

export const useFilterPresets = (
  projectId: number | null,
  options?: QueryOpts<FilterPresetListResponse>
) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<FilterPresetListResponse>({
    queryKey: getListFilterPresetsApiV1CGuildIdProjectsProjectIdFilterPresetsGetQueryKey(
      guildId,
      projectId!
    ),
    queryFn: () =>
      listFilterPresetsApiV1CGuildIdProjectsProjectIdFilterPresetsGet(guildId, projectId!),
    enabled: projectId !== null && Number.isFinite(projectId) && userEnabled,
    // The client keeps previous data by default, which across a project switch
    // would show the last project's presets — and its `can_manage`, which gates
    // the curation controls. Showing one project's permissions while another
    // loads is not a stale list, it is the wrong answer, so this query opts out.
    placeholderData: undefined,
    ...rest,
  });
};

export const useCreateFilterPreset = (
  projectId: number,
  options?: MutationOpts<FilterPresetRead, FilterPresetCreate>
) =>
  useGuildMutation<FilterPresetRead, FilterPresetCreate>(
    {
      mutationFn: (guildId, data) =>
        createFilterPresetApiV1CGuildIdProjectsProjectIdFilterPresetsPost(guildId, projectId, data),
      invalidate: () => invalidate(q.projectFilterPresets(projectId)),
      errorKey: "projects:filters.presetSaveError",
    },
    options
  );

export const useUpdateFilterPreset = (
  projectId: number,
  options?: MutationOpts<FilterPresetRead, { presetId: number; data: FilterPresetUpdate }>
) =>
  useGuildMutation<FilterPresetRead, { presetId: number; data: FilterPresetUpdate }>(
    {
      mutationFn: (guildId, { presetId, data }) =>
        updateFilterPresetApiV1CGuildIdProjectsProjectIdFilterPresetsPresetIdPatch(
          guildId,
          projectId,
          presetId,
          data
        ),
      invalidate: () => invalidate(q.projectFilterPresets(projectId)),
      errorKey: "projects:filters.presetSaveError",
    },
    options
  );

export const useDeleteFilterPreset = (projectId: number, options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, presetId) =>
        deleteFilterPresetApiV1CGuildIdProjectsProjectIdFilterPresetsPresetIdDelete(
          guildId,
          projectId,
          presetId
        ),
      invalidate: () => invalidate(q.projectFilterPresets(projectId)),
      errorKey: "projects:filters.presetDeleteError",
    },
    options
  );

export const useReorderFilterPresets = (
  projectId: number,
  options?: MutationOpts<FilterPresetRead[], FilterPresetReorderRequest>
) =>
  useGuildMutation<FilterPresetRead[], FilterPresetReorderRequest>(
    {
      mutationFn: (guildId, data) =>
        reorderFilterPresetsApiV1CGuildIdProjectsProjectIdFilterPresetsReorderPost(
          guildId,
          projectId,
          data
        ),
      invalidate: () => invalidate(q.projectFilterPresets(projectId)),
      errorKey: "projects:filters.presetSaveError",
    },
    options
  );
