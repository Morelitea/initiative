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
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
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
      ) as unknown as Promise<PropertyDefinitionRead[]>,
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
      getPropertyDefinitionApiV1GGuildIdPropertyDefinitionsDefinitionIdGet(
        guildId,
        propertyId!
      ) as unknown as Promise<PropertyDefinitionRead>,
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
      ) as unknown as Promise<PropertyEntitiesResult>,
    enabled: !!propertyId,
    staleTime: 30 * 1000,
  });
};

// ── Mutations ────────────────────────────────────────────────────────────────

export const useCreateProperty = (
  options?: MutationOpts<PropertyDefinitionRead, PropertyDefinitionCreate>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const guildId = useActiveGuildId();

  return useMutation({
    ...rest,
    mutationFn: async (data: PropertyDefinitionCreate) => {
      return createPropertyDefinitionApiV1GGuildIdPropertyDefinitionsPost(
        guildId,
        data
      ) as unknown as Promise<PropertyDefinitionRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllProperties();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "properties:manager.createError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useUpdateProperty = (
  options?: MutationOpts<
    PropertyDefinitionUpdateResponse,
    { propertyId: number; data: PropertyDefinitionUpdate }
  >
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const guildId = useActiveGuildId();

  return useMutation({
    ...rest,
    mutationFn: async ({
      propertyId,
      data,
    }: {
      propertyId: number;
      data: PropertyDefinitionUpdate;
    }) => {
      return updatePropertyDefinitionApiV1GGuildIdPropertyDefinitionsDefinitionIdPatch(
        guildId,
        propertyId,
        data
      ) as unknown as Promise<PropertyDefinitionUpdateResponse>;
    },
    onSuccess: (...args) => {
      void invalidateAllProperties();
      // Embedded summaries on documents/tasks/events need to pick up
      // name/options/color changes.
      void invalidateAllDocuments();
      void invalidateAllTasks();
      void invalidateAllCalendarEvents();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "properties:manager.updateError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteProperty = (options?: MutationOpts<void, number>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const guildId = useActiveGuildId();

  return useMutation({
    ...rest,
    mutationFn: async (propertyId: number) => {
      await deletePropertyDefinitionApiV1GGuildIdPropertyDefinitionsDefinitionIdDelete(
        guildId,
        propertyId
      );
    },
    onSuccess: (...args) => {
      void invalidateAllProperties();
      void invalidateAllDocuments();
      void invalidateAllTasks();
      void invalidateAllCalendarEvents();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "properties:manager.deleteError"));
      onError?.(...args);
    },
    onSettled,
  });
};

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
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const guildId = useActiveGuildId();

  return useMutation({
    ...rest,
    mutationFn: async ({
      documentId,
      values,
    }: {
      documentId: number;
      values: PropertyValuesSetRequest;
    }) => {
      return setDocumentPropertiesApiV1GGuildIdDocumentsDocumentIdPropertiesPut(
        guildId,
        documentId,
        values
      ) as unknown as Promise<DocumentRead>;
    },
    onSuccess: (data, variables, ...rest2) => {
      void invalidateAllDocuments();
      void invalidateDocument(variables.documentId);
      onSuccess?.(data, variables, ...rest2);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "properties:manager.setValuesError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useSetTaskProperties = (
  options?: MutationOpts<TaskRead, { taskId: number; values: PropertyValuesSetRequest }>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const guildId = useActiveGuildId();

  return useMutation({
    ...rest,
    mutationFn: async ({
      taskId,
      values,
    }: {
      taskId: number;
      values: PropertyValuesSetRequest;
    }) => {
      return setTaskPropertiesApiV1GGuildIdTasksTaskIdPropertiesPut(
        guildId,
        taskId,
        values
      ) as unknown as Promise<TaskRead>;
    },
    onSuccess: (data, variables, ...rest2) => {
      void invalidateAllTasks();
      void invalidateTask(variables.taskId);
      onSuccess?.(data, variables, ...rest2);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "properties:manager.setValuesError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useSetEventProperties = (
  options?: MutationOpts<CalendarEventRead, { eventId: number; values: PropertyValuesSetRequest }>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const guildId = useActiveGuildId();

  return useMutation({
    ...rest,
    mutationFn: async ({
      eventId,
      values,
    }: {
      eventId: number;
      values: PropertyValuesSetRequest;
    }) => {
      return setEventPropertiesApiV1GGuildIdCalendarEventsEventIdPropertiesPut(
        guildId,
        eventId,
        values
      ) as unknown as Promise<CalendarEventRead>;
    },
    onSuccess: (data, variables, ...rest2) => {
      void invalidateAllCalendarEvents();
      void invalidateCalendarEvent(variables.eventId);
      onSuccess?.(data, variables, ...rest2);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "properties:manager.setValuesError"));
      onError?.(...args);
    },
    onSettled,
  });
};
