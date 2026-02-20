import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  listDocumentsApiV1DocumentsGet,
  getListDocumentsApiV1DocumentsGetQueryKey,
  readDocumentApiV1DocumentsDocumentIdGet,
  getReadDocumentApiV1DocumentsDocumentIdGetQueryKey,
  getDocumentCountsApiV1DocumentsCountsGet,
  getGetDocumentCountsApiV1DocumentsCountsGetQueryKey,
  deleteDocumentApiV1DocumentsDocumentIdDelete,
  copyDocumentApiV1DocumentsDocumentIdCopyPost,
  updateDocumentApiV1DocumentsDocumentIdPatch,
} from "@/api/generated/documents/documents";
import { invalidateAllDocuments } from "@/api/query-keys";
import type { DocumentCountsResponse, DocumentListResponse, DocumentRead } from "@/types/api";
import type {
  ListDocumentsApiV1DocumentsGetParams,
  GetDocumentCountsApiV1DocumentsCountsGetParams,
  DocumentUpdate,
} from "@/api/generated/initiativeAPI.schemas";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useDocumentsList = (params: ListDocumentsApiV1DocumentsGetParams) => {
  return useQuery<DocumentListResponse>({
    queryKey: getListDocumentsApiV1DocumentsGetQueryKey(params),
    queryFn: () =>
      listDocumentsApiV1DocumentsGet(params) as unknown as Promise<DocumentListResponse>,
    placeholderData: keepPreviousData,
  });
};

export const useDocument = (documentId: number | null) => {
  return useQuery<DocumentRead>({
    queryKey: getReadDocumentApiV1DocumentsDocumentIdGetQueryKey(documentId!),
    queryFn: () =>
      readDocumentApiV1DocumentsDocumentIdGet(documentId!) as unknown as Promise<DocumentRead>,
    enabled: documentId !== null && Number.isFinite(documentId),
  });
};

export const useDocumentCounts = (
  params: GetDocumentCountsApiV1DocumentsCountsGetParams,
  options?: { enabled?: boolean }
) => {
  return useQuery<DocumentCountsResponse>({
    queryKey: getGetDocumentCountsApiV1DocumentsCountsGetQueryKey(params),
    queryFn: () =>
      getDocumentCountsApiV1DocumentsCountsGet(
        params
      ) as unknown as Promise<DocumentCountsResponse>,
    enabled: options?.enabled,
  });
};

// ── Prefetch helper ─────────────────────────────────────────────────────────

export const prefetchDocumentsList = (
  qc: ReturnType<typeof useQueryClient>,
  params: ListDocumentsApiV1DocumentsGetParams
) => {
  return qc.prefetchQuery({
    queryKey: getListDocumentsApiV1DocumentsGetQueryKey(params),
    queryFn: () =>
      listDocumentsApiV1DocumentsGet(params) as unknown as Promise<DocumentListResponse>,
    staleTime: 30_000,
  });
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
