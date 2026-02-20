import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  listDocumentsApiV1DocumentsGet,
  getListDocumentsApiV1DocumentsGetQueryKey,
  readDocumentApiV1DocumentsDocumentIdGet,
  getReadDocumentApiV1DocumentsDocumentIdGetQueryKey,
  getDocumentCountsApiV1DocumentsCountsGet,
  getGetDocumentCountsApiV1DocumentsCountsGetQueryKey,
  getBacklinksApiV1DocumentsDocumentIdBacklinksGet,
  getGetBacklinksApiV1DocumentsDocumentIdBacklinksGetQueryKey,
  deleteDocumentApiV1DocumentsDocumentIdDelete,
  copyDocumentApiV1DocumentsDocumentIdCopyPost,
  updateDocumentApiV1DocumentsDocumentIdPatch,
} from "@/api/generated/documents/documents";
import { invalidateAllDocuments } from "@/api/query-keys";
import type {
  DocumentCountsResponse,
  DocumentListResponse,
  DocumentRead,
} from "@/api/generated/initiativeAPI.schemas";
import type {
  ListDocumentsApiV1DocumentsGetParams,
  GetDocumentCountsApiV1DocumentsCountsGetParams,
  DocumentUpdate,
  DocumentBacklink,
  DocumentSummary,
} from "@/api/generated/initiativeAPI.schemas";

type QueryOpts<T> = Omit<UseQueryOptions<T>, "queryKey" | "queryFn">;

// ── Queries ─────────────────────────────────────────────────────────────────

export const useDocumentsList = (params: ListDocumentsApiV1DocumentsGetParams) => {
  return useQuery<DocumentListResponse>({
    queryKey: getListDocumentsApiV1DocumentsGetQueryKey(params),
    queryFn: () =>
      listDocumentsApiV1DocumentsGet(params) as unknown as Promise<DocumentListResponse>,
    placeholderData: keepPreviousData,
  });
};

export const useDocument = (documentId: number | null, options?: QueryOpts<DocumentRead>) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<DocumentRead>({
    queryKey: getReadDocumentApiV1DocumentsDocumentIdGetQueryKey(documentId!),
    queryFn: () =>
      readDocumentApiV1DocumentsDocumentIdGet(documentId!) as unknown as Promise<DocumentRead>,
    enabled: documentId !== null && Number.isFinite(documentId) && userEnabled,
    ...rest,
  });
};

export const useDocumentCounts = (
  params: GetDocumentCountsApiV1DocumentsCountsGetParams,
  options?: QueryOpts<DocumentCountsResponse>
) => {
  return useQuery<DocumentCountsResponse>({
    queryKey: getGetDocumentCountsApiV1DocumentsCountsGetQueryKey(params),
    queryFn: () =>
      getDocumentCountsApiV1DocumentsCountsGet(
        params
      ) as unknown as Promise<DocumentCountsResponse>,
    ...options,
  });
};

export const useAllDocumentIds = (options?: QueryOpts<DocumentSummary[]>) => {
  return useQuery<DocumentSummary[]>({
    queryKey: getListDocumentsApiV1DocumentsGetQueryKey({ page_size: 0 }),
    queryFn: async () => {
      const response = await (listDocumentsApiV1DocumentsGet({
        page_size: 0,
      }) as unknown as Promise<{ items: DocumentSummary[] }>);
      return response.items;
    },
    ...options,
  });
};

export const useInitiativeDocuments = (
  initiativeId: number,
  options?: QueryOpts<DocumentSummary[]>
) => {
  return useQuery<DocumentSummary[]>({
    queryKey: getListDocumentsApiV1DocumentsGetQueryKey({
      initiative_id: initiativeId,
      page_size: 0,
    }),
    queryFn: async () => {
      const response = await (listDocumentsApiV1DocumentsGet({
        initiative_id: initiativeId,
        page_size: 0,
      }) as unknown as Promise<{ items: DocumentSummary[] }>);
      return response.items;
    },
    ...options,
  });
};

export const useDocumentBacklinks = (
  documentId: number,
  options?: QueryOpts<DocumentBacklink[]>
) => {
  return useQuery<DocumentBacklink[]>({
    queryKey: getGetBacklinksApiV1DocumentsDocumentIdBacklinksGetQueryKey(documentId),
    queryFn: () =>
      getBacklinksApiV1DocumentsDocumentIdBacklinksGet(documentId) as unknown as Promise<
        DocumentBacklink[]
      >,
    ...options,
  });
};

// ── Cache helpers ───────────────────────────────────────────────────────────

export const useSetDocumentCache = () => {
  const qc = useQueryClient();
  return (
    documentId: number,
    data: DocumentRead | ((prev: DocumentRead | undefined) => DocumentRead | undefined)
  ) => {
    qc.setQueryData<DocumentRead>(
      getReadDocumentApiV1DocumentsDocumentIdGetQueryKey(documentId),
      typeof data === "function" ? data : () => data
    );
  };
};

// ── Global (cross-guild) queries ────────────────────────────────────────────

import { apiClient } from "@/api/client";

export const GLOBAL_DOCUMENTS_QUERY_KEY = "/api/v1/documents/" as const;

export const globalDocumentsQueryFn = async (
  params: Record<string, string | string[] | number | number[]>
) => {
  const response = await apiClient.get<DocumentListResponse>("/documents/", { params });
  return response.data;
};

export const useGlobalDocuments = (
  params: Record<string, string | string[] | number | number[]>,
  options?: QueryOpts<DocumentListResponse>
) => {
  return useQuery<DocumentListResponse>({
    queryKey: [GLOBAL_DOCUMENTS_QUERY_KEY, params],
    queryFn: () => globalDocumentsQueryFn(params),
    ...options,
  });
};

export const usePrefetchGlobalDocuments = () => {
  const qc = useQueryClient();
  return (params: Record<string, string | string[] | number | number[]>) => {
    return qc.prefetchQuery({
      queryKey: [GLOBAL_DOCUMENTS_QUERY_KEY, params],
      queryFn: () => globalDocumentsQueryFn(params),
      staleTime: 30_000,
    });
  };
};

// ── Prefetch helpers ────────────────────────────────────────────────────────

export const usePrefetchDocumentsList = () => {
  const qc = useQueryClient();
  return (params: ListDocumentsApiV1DocumentsGetParams) => {
    return qc.prefetchQuery({
      queryKey: getListDocumentsApiV1DocumentsGetQueryKey(params),
      queryFn: () =>
        listDocumentsApiV1DocumentsGet(params) as unknown as Promise<DocumentListResponse>,
      staleTime: 30_000,
    });
  };
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useUpdateDocument = () => {
  const { t } = useTranslation("documents");
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ documentId, data }: { documentId: number; data: DocumentUpdate }) => {
      return updateDocumentApiV1DocumentsDocumentIdPatch(
        documentId,
        data
      ) as unknown as Promise<DocumentRead>;
    },
    onSuccess: (updated, { documentId }) => {
      queryClient.setQueryData(
        getReadDocumentApiV1DocumentsDocumentIdGetQueryKey(documentId),
        updated
      );
      void invalidateAllDocuments();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("detail.saveError");
      toast.error(message);
    },
  });
};

export const useDeleteDocument = () => {
  const { t } = useTranslation("documents");

  return useMutation({
    mutationFn: async (documentIds: number[]) => {
      await Promise.all(documentIds.map((id) => deleteDocumentApiV1DocumentsDocumentIdDelete(id)));
    },
    onSuccess: (_data, documentIds) => {
      toast.success(t("bulk.deleted", { count: documentIds.length }));
      void invalidateAllDocuments();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("bulk.deleteError");
      toast.error(message);
    },
  });
};

export const useCopyDocument = () => {
  const { t } = useTranslation("documents");

  return useMutation({
    mutationFn: async (documents: { id: number; initiative_id: number; title: string }[]) => {
      const results = await Promise.all(
        documents.map(
          (doc) =>
            copyDocumentApiV1DocumentsDocumentIdCopyPost(doc.id, {
              target_initiative_id: doc.initiative_id,
              title: `${doc.title} (copy)`,
            }) as unknown as Promise<DocumentRead>
        )
      );
      return results;
    },
    onSuccess: (data) => {
      toast.success(t("bulk.duplicated", { count: data.length }));
      void invalidateAllDocuments();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("bulk.duplicateError");
      toast.error(message);
    },
  });
};
