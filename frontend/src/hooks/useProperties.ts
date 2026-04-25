import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { toast } from "@/lib/chesterToast";
import {
  listPropertyDefinitionsApiV1PropertyDefinitionsGet,
  getListPropertyDefinitionsApiV1PropertyDefinitionsGetQueryKey,
  getPropertyDefinitionApiV1PropertyDefinitionsDefinitionIdGet,
  getGetPropertyDefinitionApiV1PropertyDefinitionsDefinitionIdGetQueryKey,
  createPropertyDefinitionApiV1PropertyDefinitionsPost,
  updatePropertyDefinitionApiV1PropertyDefinitionsDefinitionIdPatch,
  deletePropertyDefinitionApiV1PropertyDefinitionsDefinitionIdDelete,
  getPropertyEntitiesApiV1PropertyDefinitionsDefinitionIdEntitiesGet,
  getGetPropertyEntitiesApiV1PropertyDefinitionsDefinitionIdEntitiesGetQueryKey,
} from "@/api/generated/property-definitions/property-definitions";
import { setDocumentPropertiesApiV1DocumentsDocumentIdPropertiesPut } from "@/api/generated/documents/documents";
import { setTaskPropertiesApiV1TasksTaskIdPropertiesPut } from "@/api/generated/tasks/tasks";
import { setEventPropertiesApiV1CalendarEventsEventIdPropertiesPut } from "@/api/generated/calendar-events/calendar-events";
import {
  invalidateAllProperties,
  invalidateAllDocuments,
  invalidateAllTasks,
  invalidateAllCalendarEvents,
  invalidateCalendarEvent,
  invalidateDocument,
  invalidateTask,
} from "@/api/query-keys";
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
import type { MutationOpts } from "@/types/mutation";
import { buildUniqueOptionSlug, findOptionByLabel } from "@/components/properties/propertyHelpers";

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
  const initiativeId = options?.initiativeId;
  const params: { initiative_id?: number } = {};
  if (initiativeId !== undefined) params.initiative_id = initiativeId;
  const hasParams = Object.keys(params).length > 0;
  return useQuery<PropertyDefinitionRead[]>({
    queryKey: getListPropertyDefinitionsApiV1PropertyDefinitionsGetQueryKey(
      hasParams ? params : undefined
    ),
    queryFn: () =>
      listPropertyDefinitionsApiV1PropertyDefinitionsGet(
        hasParams ? params : undefined
      ) as unknown as Promise<PropertyDefinitionRead[]>,
    staleTime: 60 * 1000,
  });
};

export const useProperty = (propertyId: number | null) => {
  return useQuery<PropertyDefinitionRead>({
    queryKey: getGetPropertyDefinitionApiV1PropertyDefinitionsDefinitionIdGetQueryKey(propertyId!),
    queryFn: () =>
      getPropertyDefinitionApiV1PropertyDefinitionsDefinitionIdGet(
        propertyId!
      ) as unknown as Promise<PropertyDefinitionRead>,
    enabled: !!propertyId,
    staleTime: 60 * 1000,
  });
};

export const usePropertyEntities = (propertyId: number | null) => {
  return useQuery<PropertyEntitiesResult>({
    queryKey: getGetPropertyEntitiesApiV1PropertyDefinitionsDefinitionIdEntitiesGetQueryKey(
      propertyId!
    ),
    queryFn: () =>
      getPropertyEntitiesApiV1PropertyDefinitionsDefinitionIdEntitiesGet(
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
  const { t } = useTranslation("properties");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: PropertyDefinitionCreate) => {
      return createPropertyDefinitionApiV1PropertyDefinitionsPost(
        data
      ) as unknown as Promise<PropertyDefinitionRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllProperties();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      const message = args[0] instanceof Error ? args[0].message : t("manager.createError");
      toast.error(message);
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
  const { t } = useTranslation("properties");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      propertyId,
      data,
    }: {
      propertyId: number;
      data: PropertyDefinitionUpdate;
    }) => {
      return updatePropertyDefinitionApiV1PropertyDefinitionsDefinitionIdPatch(
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
      const message = args[0] instanceof Error ? args[0].message : t("manager.updateError");
      toast.error(message);
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteProperty = (options?: MutationOpts<void, number>) => {
  const { t } = useTranslation("properties");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (propertyId: number) => {
      await deletePropertyDefinitionApiV1PropertyDefinitionsDefinitionIdDelete(propertyId);
    },
    onSuccess: (...args) => {
      void invalidateAllProperties();
      void invalidateAllDocuments();
      void invalidateAllTasks();
      void invalidateAllCalendarEvents();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      const message = args[0] instanceof Error ? args[0].message : t("manager.deleteError");
      toast.error(message);
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
      await updatePropertyDefinitionApiV1PropertyDefinitionsDefinitionIdPatch(vars.definition.id, {
        options: nextOptions,
      });
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
  const { t } = useTranslation("properties");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      documentId,
      values,
    }: {
      documentId: number;
      values: PropertyValuesSetRequest;
    }) => {
      return setDocumentPropertiesApiV1DocumentsDocumentIdPropertiesPut(
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
      const message = args[0] instanceof Error ? args[0].message : t("manager.setValuesError");
      toast.error(message);
      onError?.(...args);
    },
    onSettled,
  });
};

export const useSetTaskProperties = (
  options?: MutationOpts<TaskRead, { taskId: number; values: PropertyValuesSetRequest }>
) => {
  const { t } = useTranslation("properties");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      taskId,
      values,
    }: {
      taskId: number;
      values: PropertyValuesSetRequest;
    }) => {
      return setTaskPropertiesApiV1TasksTaskIdPropertiesPut(
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
      const message = args[0] instanceof Error ? args[0].message : t("manager.setValuesError");
      toast.error(message);
      onError?.(...args);
    },
    onSettled,
  });
};

export const useSetEventProperties = (
  options?: MutationOpts<CalendarEventRead, { eventId: number; values: PropertyValuesSetRequest }>
) => {
  const { t } = useTranslation("properties");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      eventId,
      values,
    }: {
      eventId: number;
      values: PropertyValuesSetRequest;
    }) => {
      return setEventPropertiesApiV1CalendarEventsEventIdPropertiesPut(
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
      const message = args[0] instanceof Error ? args[0].message : t("manager.setValuesError");
      toast.error(message);
      onError?.(...args);
    },
    onSettled,
  });
};
