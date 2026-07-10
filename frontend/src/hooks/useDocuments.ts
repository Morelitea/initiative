import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import {
  copyDocumentApiV1GGuildIdDocumentsDocumentIdCopyPost,
  createDocumentApiV1GGuildIdDocumentsPost,
  deleteDocumentApiV1GGuildIdDocumentsDocumentIdDelete,
  deleteDocumentVersionApiV1GGuildIdDocumentsDocumentIdVersionsVersionIdDelete,
  duplicateDocumentApiV1GGuildIdDocumentsDocumentIdDuplicatePost,
  generateSummaryApiV1GGuildIdDocumentsDocumentIdAiSummaryPost,
  getBacklinksApiV1GGuildIdDocumentsDocumentIdBacklinksGet,
  getDocumentCountsApiV1GGuildIdDocumentsCountsGet,
  getGetBacklinksApiV1GGuildIdDocumentsDocumentIdBacklinksGetQueryKey,
  getGetDocumentCountsApiV1GGuildIdDocumentsCountsGetQueryKey,
  getListDocumentsApiV1GGuildIdDocumentsGetQueryKey,
  getListDocumentVersionsApiV1GGuildIdDocumentsDocumentIdVersionsGetQueryKey,
  getReadDocumentApiV1GGuildIdDocumentsDocumentIdGetQueryKey,
  listDocumentsApiV1GGuildIdDocumentsGet,
  listDocumentVersionsApiV1GGuildIdDocumentsDocumentIdVersionsGet,
  readDocumentApiV1GGuildIdDocumentsDocumentIdGet,
  setDocumentGrantsApiV1GGuildIdDocumentsDocumentIdGrantsPut,
  updateDocumentApiV1GGuildIdDocumentsDocumentIdPatch,
  uploadDocumentFileApiV1GGuildIdDocumentsUploadPost,
  uploadDocumentVersionApiV1GGuildIdDocumentsDocumentIdVersionsPost,
} from "@/api/generated/documents/documents";
import type {
  BodyUploadDocumentFileApiV1GGuildIdDocumentsUploadPost,
  BodyUploadDocumentVersionApiV1GGuildIdDocumentsDocumentIdVersionsPost,
  DocumentBacklink,
  DocumentCountsResponse,
  DocumentCreate,
  DocumentFileVersionRead,
  DocumentListResponse,
  DocumentRead,
  DocumentSummary,
  DocumentUpdate,
  GenerateDocumentSummaryResponse,
  GetDocumentCountsApiV1GGuildIdDocumentsCountsGetParams,
  ListDocumentsApiV1GGuildIdDocumentsGetParams,
  ResourceGrantSchema,
} from "@/api/generated/initiativeAPI.schemas";
import { attachProjectDocumentApiV1GGuildIdProjectsProjectIdDocumentsDocumentIdPost } from "@/api/generated/projects/projects";
import {
  invalidateAllDocuments,
  invalidateDocument,
  invalidateDocumentVersions,
  invalidateProject,
} from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { fetchAllPages } from "@/lib/fetchAllPages";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useDocumentsList = (
  params: ListDocumentsApiV1GGuildIdDocumentsGetParams,
  options?: QueryOpts<DocumentListResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<DocumentListResponse>({
    queryKey: getListDocumentsApiV1GGuildIdDocumentsGetQueryKey(guildId, params),
    // page_size=0 walks the server's fetch-all windows for the complete set.
    queryFn: () => fetchAllPages(listDocumentsApiV1GGuildIdDocumentsGet, guildId, params),
    placeholderData: keepPreviousData,
    ...options,
  });
};

export const useDocument = (documentId: number | null, options?: QueryOpts<DocumentRead>) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<DocumentRead>({
    queryKey: getReadDocumentApiV1GGuildIdDocumentsDocumentIdGetQueryKey(guildId, documentId!),
    queryFn: () =>
      readDocumentApiV1GGuildIdDocumentsDocumentIdGet(
        guildId,
        documentId!
      ) as unknown as Promise<DocumentRead>,
    enabled: documentId !== null && Number.isFinite(documentId) && userEnabled,
    ...rest,
  });
};

export const useDocumentCounts = (
  params: GetDocumentCountsApiV1GGuildIdDocumentsCountsGetParams,
  options?: QueryOpts<DocumentCountsResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<DocumentCountsResponse>({
    queryKey: getGetDocumentCountsApiV1GGuildIdDocumentsCountsGetQueryKey(guildId, params),
    queryFn: () =>
      getDocumentCountsApiV1GGuildIdDocumentsCountsGet(
        guildId,
        params
      ) as unknown as Promise<DocumentCountsResponse>,
    ...options,
  });
};

export const useAllDocumentIds = (options?: QueryOpts<DocumentSummary[]>) => {
  const guildId = useActiveGuildId();
  return useQuery<DocumentSummary[]>({
    // Distinct key from useDocumentsList({ page_size: 0 }) — the extra
    // "items" segment prevents cache collisions with the paginated variant.
    queryKey: [
      ...getListDocumentsApiV1GGuildIdDocumentsGetQueryKey(guildId, { page_size: 0 }),
      "items",
    ],
    queryFn: async () => {
      const response = await fetchAllPages(listDocumentsApiV1GGuildIdDocumentsGet, guildId, {
        page_size: 0,
      });
      return response.items;
    },
    ...options,
  });
};

export const useInitiativeDocuments = (
  initiativeId: number,
  options?: QueryOpts<DocumentSummary[]>
) => {
  const guildId = useActiveGuildId();
  return useQuery<DocumentSummary[]>({
    queryKey: getListDocumentsApiV1GGuildIdDocumentsGetQueryKey(guildId, {
      initiative_id: initiativeId,
      page_size: 0,
    }),
    queryFn: async () => {
      const response = await fetchAllPages(listDocumentsApiV1GGuildIdDocumentsGet, guildId, {
        initiative_id: initiativeId,
        page_size: 0,
      });
      return response.items;
    },
    ...options,
  });
};

export const useDocumentBacklinks = (
  documentId: number,
  options?: QueryOpts<DocumentBacklink[]>
) => {
  const guildId = useActiveGuildId();
  return useQuery<DocumentBacklink[]>({
    queryKey: getGetBacklinksApiV1GGuildIdDocumentsDocumentIdBacklinksGetQueryKey(
      guildId,
      documentId
    ),
    queryFn: () =>
      getBacklinksApiV1GGuildIdDocumentsDocumentIdBacklinksGet(
        guildId,
        documentId
      ) as unknown as Promise<DocumentBacklink[]>,
    ...options,
  });
};

// ── Cache helpers ───────────────────────────────────────────────────────────

export const useSetDocumentCache = () => {
  const qc = useQueryClient();
  const guildId = useActiveGuildId();
  return (
    documentId: number,
    data: DocumentRead | ((prev: DocumentRead | undefined) => DocumentRead | undefined)
  ) => {
    qc.setQueryData<DocumentRead>(
      getReadDocumentApiV1GGuildIdDocumentsDocumentIdGetQueryKey(guildId, documentId),
      typeof data === "function" ? data : () => data
    );
  };
};

// ── Global (cross-guild) queries ────────────────────────────────────────────

import { apiClient } from "@/api/client";

export const GLOBAL_DOCUMENTS_QUERY_KEY = "/api/v1/me/documents" as const;

export const globalDocumentsQueryFn = async (
  params: Record<string, string | string[] | number | number[]>
) => {
  const response = await apiClient.get<DocumentListResponse>("/me/documents", { params });
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
  const guildId = useActiveGuildId();
  return (params: ListDocumentsApiV1GGuildIdDocumentsGetParams) => {
    return qc.prefetchQuery({
      queryKey: getListDocumentsApiV1GGuildIdDocumentsGetQueryKey(guildId, params),
      queryFn: () => fetchAllPages(listDocumentsApiV1GGuildIdDocumentsGet, guildId, params),
      staleTime: 30_000,
    });
  };
};

// ── Mutations ───────────────────────────────────────────────────────────────

// Helper: apply a document's full sharing state via a follow-up grants PUT (for
// copy/upload paths where the create payload can't carry them). Returns 1 if the
// call failed, else 0.
const applyDocumentGrants = async (
  guildId: number,
  documentId: number,
  grants: ResourceGrantSchema[]
): Promise<number> => {
  if (grants.length === 0) return 0;
  try {
    await setDocumentGrantsApiV1GGuildIdDocumentsDocumentIdGrantsPut(guildId, documentId, grants);
    return 0;
  } catch {
    return 1;
  }
};

export type CreateDocumentInput = {
  title: string;
  initiative_id: number;
  is_template?: boolean;
  template_id?: number;
  project_id?: number;
  /** Omit for native (text) documents; file uploads go through useUploadDocument instead. */
  document_type?: "native" | "whiteboard" | "smart_link" | "spreadsheet";
  /** Required for smart_link ({ url: "..." }). Optional/unused for other types. */
  content?: Record<string, unknown>;
  /** Full non-owner sharing state for the new document. */
  grants?: ResourceGrantSchema[];
};

export const useCreateDocument = (options?: MutationOpts<DocumentRead, CreateDocumentInput>) => {
  const { t } = useTranslation("documents");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: CreateDocumentInput) => {
      const {
        title,
        initiative_id,
        is_template,
        template_id,
        project_id,
        document_type,
        content,
        grants = [],
      } = data;

      let newDocument: DocumentRead;

      if (template_id) {
        // Copy from template
        newDocument = (await copyDocumentApiV1GGuildIdDocumentsDocumentIdCopyPost(
          guildId,
          template_id,
          {
            target_initiative_id: initiative_id,
            title,
          }
        )) as unknown as DocumentRead;
        // Template copy can't carry grants in payload — apply separately
        const failures = await applyDocumentGrants(guildId, newDocument.id, grants);
        if (failures > 0) {
          toast.warning(t("create.somePermissionsFailed"));
        }
      } else {
        // Direct create — pass grants in the payload (backend handles them)
        const payload: DocumentCreate = {
          title,
          initiative_id,
          is_template: is_template ?? false,
          ...(document_type ? { document_type } : {}),
          ...(content ? { content } : {}),
          ...(grants.length > 0 ? { grants } : {}),
        };
        newDocument = (await createDocumentApiV1GGuildIdDocumentsPost(
          guildId,
          payload
        )) as unknown as DocumentRead;
      }

      // Auto-attach to project if specified
      if (project_id) {
        await attachProjectDocumentApiV1GGuildIdProjectsProjectIdDocumentsDocumentIdPost(
          guildId,
          project_id,
          newDocument.id
        );
      }

      return newDocument;
    },
    onSuccess: (...args) => {
      void invalidateAllDocuments();
      const projectId = args[1].project_id;
      if (projectId) {
        void invalidateProject(projectId);
      }
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "documents:create.createError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export type UploadDocumentInput = {
  file: Blob;
  title: string;
  initiative_id: number;
  project_id?: number;
  /** Full non-owner sharing state for the uploaded document. */
  grants?: ResourceGrantSchema[];
};

export const useUploadDocument = (options?: MutationOpts<DocumentRead, UploadDocumentInput>) => {
  const { t } = useTranslation("documents");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: UploadDocumentInput) => {
      const { file, title, initiative_id, project_id, grants = [] } = data;

      const uploadBody: BodyUploadDocumentFileApiV1GGuildIdDocumentsUploadPost = {
        file,
        title,
        initiative_id,
      };
      const newDocument = (await uploadDocumentFileApiV1GGuildIdDocumentsUploadPost(
        guildId,
        uploadBody
      )) as unknown as DocumentRead;

      // Upload can't carry grants in payload — apply separately
      const failures = await applyDocumentGrants(guildId, newDocument.id, grants);
      if (failures > 0) {
        toast.warning(t("create.somePermissionsFailed"));
      }

      // Auto-attach to project if specified
      if (project_id) {
        await attachProjectDocumentApiV1GGuildIdProjectsProjectIdDocumentsDocumentIdPost(
          guildId,
          project_id,
          newDocument.id
        );
      }

      return newDocument;
    },
    onSuccess: (...args) => {
      void invalidateAllDocuments();
      const projectId = args[1].project_id;
      if (projectId) {
        void invalidateProject(projectId);
      }
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "documents:create.uploadError"));
      onError?.(...args);
    },
    onSettled,
  });
};

// ── File versions ─────────────────────────────────────────────────────────

export const useDocumentVersions = (
  documentId: number | null,
  options?: QueryOpts<DocumentFileVersionRead[]>
) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<DocumentFileVersionRead[]>({
    queryKey: getListDocumentVersionsApiV1GGuildIdDocumentsDocumentIdVersionsGetQueryKey(
      guildId,
      documentId!
    ),
    queryFn: () =>
      listDocumentVersionsApiV1GGuildIdDocumentsDocumentIdVersionsGet(
        guildId,
        documentId!
      ) as unknown as Promise<DocumentFileVersionRead[]>,
    enabled: documentId !== null && Number.isFinite(documentId) && userEnabled,
    ...rest,
  });
};

export const useUploadDocumentVersion = (
  options?: MutationOpts<DocumentFileVersionRead, { documentId: number; file: Blob }>
) => {
  const { t } = useTranslation("documents");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ documentId, file }: { documentId: number; file: Blob }) => {
      const body: BodyUploadDocumentVersionApiV1GGuildIdDocumentsDocumentIdVersionsPost = { file };
      return uploadDocumentVersionApiV1GGuildIdDocumentsDocumentIdVersionsPost(
        guildId,
        documentId,
        body
      ) as unknown as Promise<DocumentFileVersionRead>;
    },
    onSuccess: (...args) => {
      const documentId = args[1].documentId;
      void invalidateDocumentVersions(documentId);
      // Mirror file fields on the document row changed — refresh detail + lists.
      void invalidateDocument(documentId);
      void invalidateAllDocuments();
      toast.success(t("versions.uploadSuccess"));
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "documents:versions.uploadError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteDocumentVersion = (
  options?: MutationOpts<void, { documentId: number; versionId: number }>
) => {
  const { t } = useTranslation("documents");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ documentId, versionId }: { documentId: number; versionId: number }) => {
      await deleteDocumentVersionApiV1GGuildIdDocumentsDocumentIdVersionsVersionIdDelete(
        guildId,
        documentId,
        versionId
      );
    },
    onSuccess: (...args) => {
      const documentId = args[1].documentId;
      void invalidateDocumentVersions(documentId);
      void invalidateDocument(documentId);
      void invalidateAllDocuments();
      toast.success(t("versions.deleteSuccess"));
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "documents:versions.deleteError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useUpdateDocument = (
  options?: MutationOpts<DocumentRead, { documentId: number; data: DocumentUpdate }> & {
    /** If provided and returns true, the default error toast will be skipped. */
    suppressErrorToast?: (error: unknown) => boolean;
  }
) => {
  const queryClient = useQueryClient();
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, suppressErrorToast, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ documentId, data }: { documentId: number; data: DocumentUpdate }) => {
      return updateDocumentApiV1GGuildIdDocumentsDocumentIdPatch(
        guildId,
        documentId,
        data
      ) as unknown as Promise<DocumentRead>;
    },
    onSuccess: (...args) => {
      const [updated, vars] = args;
      queryClient.setQueryData(
        getReadDocumentApiV1GGuildIdDocumentsDocumentIdGetQueryKey(guildId, vars.documentId),
        updated
      );
      void invalidateAllDocuments();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      const error = args[0];
      if (!suppressErrorToast?.(error)) {
        toast.error(getErrorMessage(error, "documents:detail.saveError"));
      }
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteDocument = (
  options?: MutationOpts<void, number[]> & {
    /** If true, the default "X documents deleted" success toast is skipped so the caller can show its own. */
    suppressSuccessToast?: boolean;
  }
) => {
  const { t } = useTranslation("documents");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, suppressSuccessToast, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (documentIds: number[]) => {
      await Promise.all(
        documentIds.map((id) => deleteDocumentApiV1GGuildIdDocumentsDocumentIdDelete(guildId, id))
      );
    },
    onSuccess: (...args) => {
      const documentIds = args[1];
      if (!suppressSuccessToast) {
        toast.success(t("bulk.deleted", { count: documentIds.length }));
      }
      void invalidateAllDocuments();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "documents:bulk.deleteError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useCopyDocument = (
  options?: MutationOpts<DocumentRead[], { id: number; initiative_id: number; title: string }[]>
) => {
  const { t } = useTranslation("documents");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (documents: { id: number; initiative_id: number; title: string }[]) => {
      const results = await Promise.all(
        documents.map(
          (doc) =>
            copyDocumentApiV1GGuildIdDocumentsDocumentIdCopyPost(guildId, doc.id, {
              target_initiative_id: doc.initiative_id,
              title: `${doc.title} (copy)`,
            }) as unknown as Promise<DocumentRead>
        )
      );
      return results;
    },
    onSuccess: (...args) => {
      toast.success(t("bulk.duplicated", { count: args[0].length }));
      void invalidateAllDocuments();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "documents:bulk.duplicateError"));
      onError?.(...args);
    },
    onSettled,
  });
};

// ── Document-scoped mutations ───────────────────────────────────────────────

export const useDuplicateDocument = (
  documentId: number,
  options?: MutationOpts<DocumentRead, { title: string }>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ title }: { title: string }) => {
      return duplicateDocumentApiV1GGuildIdDocumentsDocumentIdDuplicatePost(guildId, documentId, {
        title,
      }) as unknown as Promise<DocumentRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllDocuments();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useCopyDocumentToInitiative = (
  documentId: number,
  options?: MutationOpts<DocumentRead, { target_initiative_id: number; title: string }>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: { target_initiative_id: number; title: string }) => {
      return copyDocumentApiV1GGuildIdDocumentsDocumentIdCopyPost(
        guildId,
        documentId,
        data
      ) as unknown as Promise<DocumentRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllDocuments();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useGenerateDocumentSummary = (
  documentId: number,
  options?: MutationOpts<GenerateDocumentSummaryResponse, void>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async () => {
      return generateSummaryApiV1GGuildIdDocumentsDocumentIdAiSummaryPost(
        guildId,
        documentId
      ) as unknown as Promise<GenerateDocumentSummaryResponse>;
    },
    onSuccess,
    onError,
    onSettled,
  });
};

export const useSetDocumentGrants = (
  documentId: number,
  options?: MutationOpts<DocumentRead, ResourceGrantSchema[]>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (grants: ResourceGrantSchema[]) => {
      return setDocumentGrantsApiV1GGuildIdDocumentsDocumentIdGrantsPut(
        guildId,
        documentId,
        grants
      ) as unknown as Promise<DocumentRead>;
    },
    onSuccess: (...args) => {
      void invalidateDocument(documentId);
      void invalidateAllDocuments();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "documents:settings.updateAccessError"));
      onError?.(...args);
    },
    onSettled,
  });
};
