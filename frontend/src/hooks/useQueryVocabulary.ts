/**
 * The words a statement may contain, and the fields behind each of them.
 *
 * Both halves come from the server's own registry — the datasets and functions
 * from the validator's allow-lists, the fields from the field registry — so a
 * name offered while somebody types is one the validator accepts. Neither
 * describes anybody's rows: the answer is the same for every guild and never
 * changes within a deployment, so both are cached for the session and every
 * consumer shares one request.
 */

import { useQueries, useQuery } from "@tanstack/react-query";

import {
  getReadFieldCatalogApiV1FieldsDatasetGetQueryKey,
  getReadQueryVocabularyApiV1QueryVocabularyGetQueryKey,
  readFieldCatalogApiV1FieldsDatasetGet,
  readQueryVocabularyApiV1QueryVocabularyGet,
} from "@/api/generated/fields/fields";
import type { DatasetName } from "@/api/generated/initiativeAPI.schemas";
import type { DatasetFields } from "@/lib/widgets/completion";

/** Neither answer changes while the tab is open, or after it. */
const FOREVER = {
  staleTime: Number.POSITIVE_INFINITY,
  gcTime: Number.POSITIVE_INFINITY,
} as const;

const NO_DATASETS: string[] = [];
const NO_FUNCTIONS: string[] = [];
const NO_FIELDS: DatasetFields[] = [];

/** What a statement may name and call. */
export const useQueryVocabulary = (enabled = true) => {
  const query = useQuery({
    queryKey: getReadQueryVocabularyApiV1QueryVocabularyGetQueryKey(),
    queryFn: () => readQueryVocabularyApiV1QueryVocabularyGet(),
    enabled,
    ...FOREVER,
  });
  return {
    datasets: query.data?.datasets ?? NO_DATASETS,
    functions: query.data?.functions ?? NO_FUNCTIONS,
    isLoading: query.isLoading,
  };
};

/**
 * The fields of several datasets at once.
 *
 * One query each rather than one call for all of them, so a dataset already
 * read for a filter control or the builder is not read again — the cache key is
 * the endpoint's own, so every consumer of a dataset shares the one request.
 */
export const useFieldCatalogs = (datasets: string[], enabled = true): DatasetFields[] =>
  useQueries({
    queries: datasets.map((dataset) => ({
      queryKey: getReadFieldCatalogApiV1FieldsDatasetGetQueryKey(dataset as DatasetName),
      queryFn: () => readFieldCatalogApiV1FieldsDatasetGet(dataset as DatasetName),
      enabled,
      ...FOREVER,
    })),
    // Reduced here rather than after the hook returns, so the array is stable
    // between renders and the completion list is not rebuilt on every keystroke.
    combine: (results) => {
      const answered = results
        .map((result) => result.data)
        .filter((data): data is NonNullable<typeof data> => Boolean(data))
        .map(
          (data): DatasetFields => ({
            dataset: data.dataset,
            fields: data.fields.map((field) => ({ name: field.name, type: field.type })),
          })
        );
      return answered.length ? answered : NO_FIELDS;
    },
  });
