import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

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
import {
  invalidateAllProperties,
  invalidateAllDocuments,
  invalidateAllTasks,
  invalidateDocument,
  invalidateTask,
} from "@/api/query-keys";
import type {
  DocumentRead,
  PropertyAppliesTo,
  PropertyDefinitionCreate,
  PropertyDefinitionRead,
  PropertyDefinitionUpdate,
  PropertyDefinitionUpdateResponse,
  PropertyEntitiesResult,
  PropertyValuesSetRequest,
  TaskRead,
} from "@/api/generated/initiativeAPI.schemas";
import type { MutationOpts } from "@/types/mutation";

// ── Queries ──────────────────────────────────────────────────────────────────

export const useProperties = (appliesTo?: PropertyAppliesTo) => {
  const params = appliesTo ? { applies_to: appliesTo } : undefined;
  return useQuery<PropertyDefinitionRead[]>({
    queryKey: getListPropertyDefinitionsApiV1PropertyDefinitionsGetQueryKey(params),
    queryFn: () =>
      listPropertyDefinitionsApiV1PropertyDefinitionsGet(params) as unknown as Promise<
        PropertyDefinitionRead[]
      >,
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
      // Embedded summaries on documents/tasks need to pick up name/options/color changes.
      void invalidateAllDocuments();
      void invalidateAllTasks();
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
