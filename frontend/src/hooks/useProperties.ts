import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { setEventPropertiesApiV1GGuildIdCalendarEventsEventIdPropertiesPut } from "@/api/generated/calendar-events/calendar-events";
import { setDocumentPropertiesApiV1GGuildIdDocumentsDocumentIdPropertiesPut } from "@/api/generated/documents/documents";
import type {
  CalendarEventRead,
  DocumentRead,
  PropertyDefinitionCreate,
  PropertyDefinitionRead,
  PropertyDefinitionUpdate,
  PropertyDefinitionUpdateResponse,
  PropertyEntitiesResult,
  PropertyOption,
  PropertyValuesSetRequest,
  TaskRead,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createPropertyDefinitionApiV1GGuildIdPropertyDefinitionsPost,
  deletePropertyDefinitionApiV1GGuildIdPropertyDefinitionsDefinitionIdDelete,
  getGetPropertyDefinitionApiV1GGuildIdPropertyDefinitionsDefinitionIdGetQueryKey,
  getGetPropertyEntitiesApiV1GGuildIdPropertyDefinitionsDefinitionIdEntitiesGetQueryKey,
  getListPropertyDefinitionsApiV1GGuildIdPropertyDefinitionsGetQueryKey,
  getPropertyDefinitionApiV1GGuildIdPropertyDefinitionsDefinitionIdGet,
  getPropertyEntitiesApiV1GGuildIdPropertyDefinitionsDefinitionIdEntitiesGet,
  listPropertyDefinitionsApiV1GGuildIdPropertyDefinitionsGet,
  updatePropertyDefinitionApiV1GGuildIdPropertyDefinitionsDefinitionIdPatch,
} from "@/api/generated/property-definitions/property-definitions";
import { setTaskPropertiesApiV1GGuildIdTasksTaskIdPropertiesPut } from "@/api/generated/tasks/tasks";
import {
  invalidateAllCalendarEvents,
  invalidateAllDocuments,
  invalidateAllProperties,
  invalidateAllTasks,
  invalidateCalendarEvent,
  invalidateDocument,
  invalidateTask,
} from "@/api/query-keys";
import { buildUniqueOptionSlug, findOptionByLabel } from "@/components/properties/propertyHelpers";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import { toast } from "@/lib/chesterToast";
import type { MutationOpts } from "@/types/mutation";

// ── Queries ──────────────────────────────────────────────────────────────────

/**
 * List property definitions.
 *
 * - ``initiativeId`` bound: scopes to that one initiative (for per-entity
 *   pickers and the initiative settings manager page).
 * - ``initiativeId`` omitted: returns the union across every initiative the
 *   caller is a member of — used by global views (My Tasks, Documents list,
 *   events list) so property columns and filters aggregate across initiatives.
 */
export const useProperties = (options?: { initiativeId?: number }) => {
  const guildId = useActiveGuildId();
  const initiativeId = options?.initiativeId;
  const params: { initiative_id?: number } = {};
  if (initiativeId !== undefined) params.initiative_id = initiativeId;
  const hasParams = Object.keys(params).length > 0;
  return useQuery<PropertyDefinitionRead[]>({
    queryKey: getListPropertyDefinitionsApiV1GGuildIdPropertyDefinitionsGetQueryKey(
      guildId,
      hasParams ? params : undefined
    ),
    queryFn: () =>
      listPropertyDefinitionsApiV1GGuildIdPropertyDefinitionsGet(
        guildId,
        hasParams ? params : undefined
      ),
    staleTime: 60 * 1000,
  });
};

export const useProperty = (propertyId: number | null) => {
  const guildId = useActiveGuildId();
  return useQuery<PropertyDefinitionRead>({
    queryKey: getGetPropertyDefinitionApiV1GGuildIdPropertyDefinitionsDefinitionIdGetQueryKey(
      guildId,
      propertyId!
    ),
    queryFn: () =>
      getPropertyDefinitionApiV1GGuildIdPropertyDefinitionsDefinitionIdGet(guildId, propertyId!),
    enabled: !!propertyId,
    staleTime: 60 * 1000,
  });
};

export const usePropertyEntities = (propertyId: number | null) => {
  const guildId = useActiveGuildId();
  return useQuery<PropertyEntitiesResult>({
    queryKey: getGetPropertyEntitiesApiV1GGuildIdPropertyDefinitionsDefinitionIdEntitiesGetQueryKey(
      guildId,
      propertyId!
    ),
    queryFn: () =>
      getPropertyEntitiesApiV1GGuildIdPropertyDefinitionsDefinitionIdEntitiesGet(
        guildId,
        propertyId!
      ),
    enabled: !!propertyId,
    staleTime: 30 * 1000,
  });
};

// ── Mutations ────────────────────────────────────────────────────────────────

export const useCreateProperty = (
  options?: MutationOpts<PropertyDefinitionRead, PropertyDefinitionCreate>
) =>
  useGuildMutation<PropertyDefinitionRead, PropertyDefinitionCreate>(
    {
      mutationFn: (guildId, data) =>
        createPropertyDefinitionApiV1GGuildIdPropertyDefinitionsPost(guildId, data),
      invalidate: () => invalidateAllProperties(),
      errorKey: "properties:manager.createError",
    },
    options
  );

export const useUpdateProperty = (
  options?: MutationOpts<
    PropertyDefinitionUpdateResponse,
    { propertyId: number; data: PropertyDefinitionUpdate }
  >
) =>
  useGuildMutation<
    PropertyDefinitionUpdateResponse,
    { propertyId: number; data: PropertyDefinitionUpdate }
  >(
    {
      mutationFn: (guildId, { propertyId, data }) =>
        updatePropertyDefinitionApiV1GGuildIdPropertyDefinitionsDefinitionIdPatch(
          guildId,
          propertyId,
          data
        ),
      invalidate: () =>
        Promise.all([
          invalidateAllProperties(),
          // Embedded summaries on documents/tasks/events need to pick up
          // name/options/color changes.
          invalidateAllDocuments(),
          invalidateAllTasks(),
          invalidateAllCalendarEvents(),
        ]),
      errorKey: "properties:manager.updateError",
    },
    options
  );

export const useDeleteProperty = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, propertyId) =>
        deletePropertyDefinitionApiV1GGuildIdPropertyDefinitionsDefinitionIdDelete(
          guildId,
          propertyId
        ),
      invalidate: () =>
        Promise.all([
          invalidateAllProperties(),
          invalidateAllDocuments(),
          invalidateAllTasks(),
          invalidateAllCalendarEvents(),
        ]),
      errorKey: "properties:manager.deleteError",
    },
    options
  );

/**
 * Append a single option to a select / multi_select definition and return
 * the newly-added option. If a case-insensitive label match already exists
 * the existing option is returned without hitting the network, so the UI
 * can use it transparently as "picked" after the user typed an existing
 * label.
 */
export const useAppendPropertyOption = () => {
  const { t } = useTranslation("properties");
  const guildId = useActiveGuildId();

  const mutation = useMutation({
    mutationFn: async (vars: {
      definition: PropertyDefinitionRead;
      label: string;
      color?: string | null;
    }) => {
      const label = vars.label.trim();
      if (!label) {
        throw new Error("Option label cannot be empty");
      }
      const existing = findOptionByLabel(vars.definition, label);
      if (existing) {
        return { option: existing, created: false as const };
      }
      const currentOptions = vars.definition.options ?? [];
      const slug = buildUniqueOptionSlug(label, currentOptions);
      const newOption: PropertyOption = {
        value: slug,
        label,
        color: vars.color ?? null,
      };
      const nextOptions: PropertyOption[] = [...currentOptions, newOption];
      await updatePropertyDefinitionApiV1GGuildIdPropertyDefinitionsDefinitionIdPatch(
        guildId,
        vars.definition.id,
        {
          options: nextOptions,
        }
      );
      return { option: newOption, created: true as const };
    },
    onSuccess: (result) => {
      void invalidateAllProperties();
      void invalidateAllDocuments();
      void invalidateAllTasks();
      void invalidateAllCalendarEvents();
      if (result.created) {
        toast.success(t("input.optionAdded"));
      }
    },
    onError: () => {
      toast.error(t("input.optionAddFailed"));
    },
  });

  return {
    appendOption: (definition: PropertyDefinitionRead, label: string, color?: string | null) =>
      mutation.mutateAsync({ definition, label, color }),
    isPending: mutation.isPending,
  };
};

export const useSetDocumentProperties = (
  options?: MutationOpts<DocumentRead, { documentId: number; values: PropertyValuesSetRequest }>
) =>
  useGuildMutation<DocumentRead, { documentId: number; values: PropertyValuesSetRequest }>(
    {
      mutationFn: (guildId, { documentId, values }) =>
        setDocumentPropertiesApiV1GGuildIdDocumentsDocumentIdPropertiesPut(
          guildId,
          documentId,
          values
        ),
      invalidate: (_data, vars) =>
        Promise.all([invalidateAllDocuments(), invalidateDocument(vars.documentId)]),
      errorKey: "properties:manager.setValuesError",
    },
    options
  );

export const useSetTaskProperties = (
  options?: MutationOpts<TaskRead, { taskId: number; values: PropertyValuesSetRequest }>
) =>
  useGuildMutation<TaskRead, { taskId: number; values: PropertyValuesSetRequest }>(
    {
      mutationFn: (guildId, { taskId, values }) =>
        setTaskPropertiesApiV1GGuildIdTasksTaskIdPropertiesPut(guildId, taskId, values),
      invalidate: (_data, vars) => Promise.all([invalidateAllTasks(), invalidateTask(vars.taskId)]),
      errorKey: "properties:manager.setValuesError",
    },
    options
  );

export const useSetEventProperties = (
  options?: MutationOpts<CalendarEventRead, { eventId: number; values: PropertyValuesSetRequest }>
) =>
  useGuildMutation<CalendarEventRead, { eventId: number; values: PropertyValuesSetRequest }>(
    {
      mutationFn: (guildId, { eventId, values }) =>
        setEventPropertiesApiV1GGuildIdCalendarEventsEventIdPropertiesPut(guildId, eventId, values),
      invalidate: (_data, vars) =>
        Promise.all([invalidateAllCalendarEvents(), invalidateCalendarEvent(vars.eventId)]),
      errorKey: "properties:manager.setValuesError",
    },
    options
  );
