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
  createFilterPresetApiV1GGuildIdProjectsProjectIdFilterPresetsPost,
  deleteFilterPresetApiV1GGuildIdProjectsProjectIdFilterPresetsPresetIdDelete,
  getListFilterPresetsApiV1GGuildIdProjectsProjectIdFilterPresetsGetQueryKey,
  listFilterPresetsApiV1GGuildIdProjectsProjectIdFilterPresetsGet,
  reorderFilterPresetsApiV1GGuildIdProjectsProjectIdFilterPresetsReorderPost,
  updateFilterPresetApiV1GGuildIdProjectsProjectIdFilterPresetsPresetIdPatch,
} from "@/api/generated/filter-presets/filter-presets";
import type {
  FilterPresetCreate,
  FilterPresetListResponse,
  FilterPresetRead,
  FilterPresetReorderRequest,
  FilterPresetUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidateProjectFilterPresets } from "@/api/query-keys";
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
    queryKey: getListFilterPresetsApiV1GGuildIdProjectsProjectIdFilterPresetsGetQueryKey(
      guildId,
      projectId!
    ),
    queryFn: () =>
      listFilterPresetsApiV1GGuildIdProjectsProjectIdFilterPresetsGet(guildId, projectId!),
    enabled: projectId !== null && Number.isFinite(projectId) && userEnabled,
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
        createFilterPresetApiV1GGuildIdProjectsProjectIdFilterPresetsPost(guildId, projectId, data),
      invalidate: () => invalidateProjectFilterPresets(projectId),
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
        updateFilterPresetApiV1GGuildIdProjectsProjectIdFilterPresetsPresetIdPatch(
          guildId,
          projectId,
          presetId,
          data
        ),
      invalidate: () => invalidateProjectFilterPresets(projectId),
      errorKey: "projects:filters.presetSaveError",
    },
    options
  );

export const useDeleteFilterPreset = (projectId: number, options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, presetId) =>
        deleteFilterPresetApiV1GGuildIdProjectsProjectIdFilterPresetsPresetIdDelete(
          guildId,
          projectId,
          presetId
        ),
      invalidate: () => invalidateProjectFilterPresets(projectId),
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
        reorderFilterPresetsApiV1GGuildIdProjectsProjectIdFilterPresetsReorderPost(
          guildId,
          projectId,
          data
        ),
      invalidate: () => invalidateProjectFilterPresets(projectId),
      errorKey: "projects:filters.presetSaveError",
    },
    options
  );
