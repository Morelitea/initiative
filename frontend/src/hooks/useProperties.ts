import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import type {
  PropertyDefinitionCreate,
  PropertyDefinitionRead,
  PropertyDefinitionUpdate,
  PropertyDefinitionUpdateResponse,
  PropertyOption,
  PropertySummary,
  PropertyTarget,
  PropertyValueInput,
} from "@/api/generated/initiativeAPI.schemas";
import { setProperties } from "@/api/generated/properties/properties";
import {
  createPropertyDefinition,
  deletePropertyDefinition,
  getListPropertyDefinitionsQueryKey,
  listPropertyDefinitions,
  updatePropertyDefinition,
} from "@/api/generated/property-definitions/property-definitions";
import { invalidate, q } from "@/api/query-keys";
import { buildUniqueOptionSlug, findOptionByLabel } from "@/components/properties/propertyHelpers";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
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
export const useProperties = (options?: { initiativeId?: number; enabled?: boolean }) => {
  const communityId = useActiveCommunityId();
  const initiativeId = options?.initiativeId;
  const params: { initiative_id?: number } = {};
  if (initiativeId !== undefined) params.initiative_id = initiativeId;
  const hasParams = Object.keys(params).length > 0;
  return useQuery<PropertyDefinitionRead[]>({
    queryKey: getListPropertyDefinitionsQueryKey(communityId, hasParams ? params : undefined),
    queryFn: () => listPropertyDefinitions(communityId, hasParams ? params : undefined),
    enabled: options?.enabled ?? true,
    staleTime: 60 * 1000,
  });
};

// ── Mutations ────────────────────────────────────────────────────────────────

export const useCreateProperty = (
  options?: MutationOpts<PropertyDefinitionRead, PropertyDefinitionCreate>
) =>
  useCommunityMutation<PropertyDefinitionRead, PropertyDefinitionCreate>(
    {
      mutationFn: (communityId, data) => createPropertyDefinition(communityId, data),
      invalidate: () => invalidate(q.allProperties()),
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
  useCommunityMutation<
    PropertyDefinitionUpdateResponse,
    { propertyId: number; data: PropertyDefinitionUpdate }
  >(
    {
      mutationFn: (communityId, { propertyId, data }) =>
        updatePropertyDefinition(communityId, propertyId, data),
      // Every row's embedded summaries carry the definition's name, options
      // and color.
      invalidate: () => invalidate(q.allProperties(), q.allPropertyHolders()),
      errorKey: "properties:manager.updateError",
    },
    options
  );

export const useDeleteProperty = (options?: MutationOpts<void, number>) =>
  useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, propertyId) => deletePropertyDefinition(communityId, propertyId),
      invalidate: () => invalidate(q.allProperties(), q.allPropertyHolders()),
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
  const communityId = useActiveCommunityId();

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
      const saved = await updatePropertyDefinition(communityId, vars.definition.id, {
        options: nextOptions,
      });
      // The server keeps options it already holds as they are, so the one
      // asked for is only there if it came back under this label.
      const stored = findOptionByLabel(saved.definition, label);
      if (!stored) {
        void invalidate(q.allProperties());
        throw new Error("Option was not added");
      }
      return { option: stored, created: true as const };
    },
    onSuccess: (result) => {
      void invalidate(q.allProperties(), q.allPropertyHolders());
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

export interface SetPropertiesVariables {
  target: PropertyTarget;
  id: number;
  /** Replace-all: every property the row keeps, an empty list clears them. */
  values: PropertyValueInput[];
}

/** Replace the property values on any tool or sub-tool row. */
export const useSetProperties = (
  options?: MutationOpts<PropertySummary[], SetPropertiesVariables>
) =>
  useCommunityMutation<PropertySummary[], SetPropertiesVariables>(
    {
      mutationFn: (communityId, { target, id, values }) =>
        setProperties(communityId, target, id, { values }),
      invalidate: (_data, vars) => invalidate(q.propertyHolder(vars.target)),
      errorKey: "properties:manager.setValuesError",
    },
    // Each write replaces every value on its row, so they run one at a time
    // in the order they were made: a later write can never be overtaken by
    // an earlier one that knew about less.
    { scope: { id: "property-values" }, ...options }
  );
