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
  getDocumentCountsByInitiativeApiV1GGuildIdDocumentsCountsByInitiativeGet,
  getGetBacklinksApiV1GGuildIdDocumentsDocumentIdBacklinksGetQueryKey,
  getGetDocumentCountsApiV1GGuildIdDocumentsCountsGetQueryKey,
  getGetDocumentCountsByInitiativeApiV1GGuildIdDocumentsCountsByInitiativeGetQueryKey,
  getListDocumentsApiV1GGuildIdDocumentsGetQueryKey,
  getListDocumentVersionsApiV1GGuildIdDocumentsDocumentIdVersionsGetQueryKey,
  getListMyDocumentsApiV1MeDocumentsGetQueryKey,
  getReadDocumentApiV1GGuildIdDocumentsDocumentIdGetQueryKey,
  listDocumentsApiV1GGuildIdDocumentsGet,
  listDocumentVersionsApiV1GGuildIdDocumentsDocumentIdVersionsGet,
  listMyDocumentsApiV1MeDocumentsGet,
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
  InitiativeGroupedCountsResponse,
  ListDocumentsApiV1GGuildIdDocumentsGetParams,
  ListMyDocumentsApiV1MeDocumentsGetParams,
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
import { useGuildMutation } from "@/hooks/useApiMutation";
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
    queryFn: () => readDocumentApiV1GGuildIdDocumentsDocumentIdGet(guildId, documentId!),
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
    queryFn: () => getDocumentCountsApiV1GGuildIdDocumentsCountsGet(guildId, params),
    ...options,
  });
};

export const useDocumentCountsByInitiative = (
  options?: QueryOpts<InitiativeGroupedCountsResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<InitiativeGroupedCountsResponse>({
    queryKey:
      getGetDocumentCountsByInitiativeApiV1GGuildIdDocumentsCountsByInitiativeGetQueryKey(guildId),
    queryFn: () =>
      getDocumentCountsByInitiativeApiV1GGuildIdDocumentsCountsByInitiativeGet(guildId),
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
    queryFn: () => getBacklinksApiV1GGuildIdDocumentsDocumentIdBacklinksGet(guildId, documentId),
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

export const useGlobalDocuments = (
  params?: ListMyDocumentsApiV1MeDocumentsGetParams,
  options?: QueryOpts<DocumentListResponse>
) => {
  return useQuery<DocumentListResponse>({
    queryKey: getListMyDocumentsApiV1MeDocumentsGetQueryKey(params),
    queryFn: () => listMyDocumentsApiV1MeDocumentsGet(params),
    ...options,
  });
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
  name: string;
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
        name,
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
        newDocument = await copyDocumentApiV1GGuildIdDocumentsDocumentIdCopyPost(
          guildId,
          template_id,
          {
            target_initiative_id: initiative_id,
            name,
          }
        );
        // Template copy can't carry grants in payload — apply separately
        const failures = await applyDocumentGrants(guildId, newDocument.id, grants);
        if (failures > 0) {
          toast.warning(t("create.somePermissionsFailed"));
        }
      } else {
        // Direct create — pass grants in the payload (backend handles them)
        const payload: DocumentCreate = {
          name,
          initiative_id,
          is_template: is_template ?? false,
          ...(document_type ? { document_type } : {}),
          ...(content ? { content } : {}),
          ...(grants.length > 0 ? { grants } : {}),
        };
        newDocument = await createDocumentApiV1GGuildIdDocumentsPost(guildId, payload);
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
  name: string;
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
      const { file, name, initiative_id, project_id, grants = [] } = data;

      const uploadBody: BodyUploadDocumentFileApiV1GGuildIdDocumentsUploadPost = {
        file,
        name,
        initiative_id,
      };
      const newDocument = await uploadDocumentFileApiV1GGuildIdDocumentsUploadPost(
        guildId,
        uploadBody
      );

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
      listDocumentVersionsApiV1GGuildIdDocumentsDocumentIdVersionsGet(guildId, documentId!),
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
      );
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
  documentId: number,
  options?: MutationOpts<DocumentRead, DocumentUpdate> & {
    /** If provided and returns true, the default error toast will be skipped. */
    suppressErrorToast?: (error: unknown) => boolean;
  }
) => {
  const queryClient = useQueryClient();
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, suppressErrorToast, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: DocumentUpdate) => {
      return updateDocumentApiV1GGuildIdDocumentsDocumentIdPatch(guildId, documentId, data);
    },
    onSuccess: (...args) => {
      const [updated] = args;
      queryClient.setQueryData(
        getReadDocumentApiV1GGuildIdDocumentsDocumentIdGetQueryKey(guildId, documentId),
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

/**
 * Single-document delete — the shape every tool's delete hook takes, so the
 * shared settings page needs no per-tool adapter. Bulk selection deletes go
 * through {@link useDeleteDocuments}.
 */
export const useDeleteDocument = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, documentId) =>
        deleteDocumentApiV1GGuildIdDocumentsDocumentIdDelete(guildId, documentId),
      invalidate: () => invalidateAllDocuments(),
      errorKey: "documents:bulk.deleteError",
    },
    options
  );

export const useDeleteDocuments = (
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
  options?: MutationOpts<DocumentRead[], { id: number; initiative_id: number; name: string }[]>
) => {
  const { t } = useTranslation("documents");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (documents: { id: number; initiative_id: number; name: string }[]) => {
      const results = await Promise.all(
        documents.map((doc) =>
          copyDocumentApiV1GGuildIdDocumentsDocumentIdCopyPost(guildId, doc.id, {
            target_initiative_id: doc.initiative_id,
            name: `${doc.name} (copy)`,
          })
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
  options?: MutationOpts<DocumentRead, { name: string }>
) =>
  useGuildMutation<DocumentRead, { name: string }>(
    {
      mutationFn: (guildId, { name }) =>
        duplicateDocumentApiV1GGuildIdDocumentsDocumentIdDuplicatePost(guildId, documentId, {
          name,
        }),
      invalidate: () => invalidateAllDocuments(),
    },
    options
  );

export const useCopyDocumentToInitiative = (
  documentId: number,
  options?: MutationOpts<DocumentRead, { target_initiative_id: number; name: string }>
) =>
  useGuildMutation<DocumentRead, { target_initiative_id: number; name: string }>(
    {
      mutationFn: (guildId, data) =>
        copyDocumentApiV1GGuildIdDocumentsDocumentIdCopyPost(guildId, documentId, data),
      invalidate: () => invalidateAllDocuments(),
    },
    options
  );

export const useGenerateDocumentSummary = (
  documentId: number,
  options?: MutationOpts<GenerateDocumentSummaryResponse, void>
) =>
  useGuildMutation<GenerateDocumentSummaryResponse, void>(
    {
      mutationFn: (guildId) =>
        generateSummaryApiV1GGuildIdDocumentsDocumentIdAiSummaryPost(guildId, documentId),
    },
    options
  );

export const useSetDocumentGrants = (
  documentId: number,
  options?: MutationOpts<DocumentRead, ResourceGrantSchema[]>
) =>
  useGuildMutation<DocumentRead, ResourceGrantSchema[]>(
    {
      mutationFn: (guildId, grants) =>
        setDocumentGrantsApiV1GGuildIdDocumentsDocumentIdGrantsPut(guildId, documentId, grants),
      invalidate: () => Promise.all([invalidateDocument(documentId), invalidateAllDocuments()]),
      errorKey: "documents:settings.updateAccessError",
    },
    options
  );
