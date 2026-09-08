/**
 * The fields a dataset offers, from the server's field registry.
 *
 * There is one declaration of what a field is — its type, the operators it
 * accepts, the control that picks a value — and it lives on the backend beside
 * the engine that compiles filters. This reads it, so a control can never offer
 * an operator the server would refuse and a new field reaches the UI without a
 * second list being edited.
 *
 * The answer describes a dataset's shape rather than anybody's rows: it is the
 * same for every guild and never changes within a deployment, so it is cached
 * indefinitely and every consumer of a dataset shares one request.
 */

import { useMemo } from "react";

import { useReadFieldCatalogApiV1FieldsDatasetGet } from "@/api/generated/fields/fields";
import type { DatasetName } from "@/api/generated/initiativeAPI.schemas";
import { type FilterFieldSpec, toFilterFieldSpec } from "@/lib/widgets/conditions";

export type { DatasetName };

const EMPTY: FilterFieldSpec[] = [];

/**
 * The declarations, ready for the controls to read.
 *
 * The mapping lives here rather than at each call site: every consumer wants
 * the same shape, and two components doing it themselves is two places to keep
 * in step for no gain.
 */
export function useFieldCatalog(dataset: DatasetName) {
  const query = useReadFieldCatalogApiV1FieldsDatasetGet(dataset, {
    query: {
      staleTime: Number.POSITIVE_INFINITY,
      gcTime: Number.POSITIVE_INFINITY,
    },
  });

  const described = query.data?.fields;
  const fields = useMemo(() => (described ? described.map(toFilterFieldSpec) : EMPTY), [described]);

  return {
    /** Empty until it loads — a filter list with nothing in it renders as
     *  nothing, which is the right thing to show while it is on its way. */
    fields,
    isLoading: query.isLoading,
  };
}
