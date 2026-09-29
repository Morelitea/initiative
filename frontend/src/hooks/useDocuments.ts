import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import {
  copyDocumentApiV1CGuildIdDocumentsDocumentIdCopyPost,
  createDocumentApiV1CGuildIdDocumentsPost,
  deleteDocumentApiV1CGuildIdDocumentsDocumentIdDelete,
  deleteDocumentVersionApiV1CGuildIdDocumentsDocumentIdVersionsVersionIdDelete,
  duplicateDocumentApiV1CGuildIdDocumentsDocumentIdDuplicatePost,
  generateSummaryApiV1CGuildIdDocumentsDocumentIdAiSummaryPost,
  getDocumentCountsApiV1CGuildIdDocumentsCountsGet,
  getGetDocumentCountsApiV1CGuildIdDocumentsCountsGetQueryKey,
  getListDocumentVersionsApiV1CGuildIdDocumentsDocumentIdVersionsGetQueryKey,
  getReadDocumentApiV1CGuildIdDocumentsDocumentIdGetQueryKey,
  listDocumentVersionsApiV1CGuildIdDocumentsDocumentIdVersionsGet,
  setDocumentGrantsApiV1CGuildIdDocumentsDocumentIdGrantsPut,
  updateDocumentApiV1CGuildIdDocumentsDocumentIdPatch,
  uploadDocumentFileApiV1CGuildIdDocumentsUploadPost,
  uploadDocumentVersionApiV1CGuildIdDocumentsDocumentIdVersionsPost,
} from "@/api/generated/documents/documents";
import type {
  BodyUploadDocumentFileApiV1CGuildIdDocumentsUploadPost,
  BodyUploadDocumentVersionApiV1CGuildIdDocumentsDocumentIdVersionsPost,
  DocumentCountsResponse,
  DocumentCreate,
  DocumentFileVersionRead,
  DocumentListResponse,
  DocumentRead,
  DocumentUpdate,
  GenerateDocumentSummaryResponse,
  GetDocumentCountsApiV1CGuildIdDocumentsCountsGetParams,
  ListDocumentsApiV1CGuildIdDocumentsGetParams,
  ResourceGrantSchema,
} from "@/api/generated/initiativeAPI.schemas";
import { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { relate } from "@/api/relationships";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── The standard four ───────────────────────────────────────────────────────
// Built in `toolHooks.ts` from the generated client; see there for the keys
// each one reads and the invalidation each one fires. A document's list hook,
// create and update are its own, and are written out below — the list's query
// still comes from the table, so the key is named in one place.

const documents = TOOL_HOOKS[Tool.document];
export const useDocument = documents.useDetail;
/**
 * Single-document delete — the shape every tool's delete hook takes, so the
 * shared settings page needs no per-tool adapter. Bulk selection deletes go
 * through {@link useDeleteDocuments}.
 */
export const useDeleteDocument = documents.useDelete;
export const useSetDocumentGrants = documents.useSetGrants;

// ── Queries ─────────────────────────────────────────────────────────────────

export const useDocumentsList = (
  params: ListDocumentsApiV1CGuildIdDocumentsGetParams,
  options?: QueryOpts<DocumentListResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<DocumentListResponse>({
    ...documents.listQuery(guildId, params),
    placeholderData: keepPreviousData,
    ...options,
  });
};

export const useDocumentCounts = (
  params: GetDocumentCountsApiV1CGuildIdDocumentsCountsGetParams,
  options?: QueryOpts<DocumentCountsResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<DocumentCountsResponse>({
    queryKey: getGetDocumentCountsApiV1CGuildIdDocumentsCountsGetQueryKey(guildId, params),
    queryFn: () => getDocumentCountsApiV1CGuildIdDocumentsCountsGet(guildId, params),
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
      getReadDocumentApiV1CGuildIdDocumentsDocumentIdGetQueryKey(guildId, documentId),
      typeof data === "function" ? data : () => data
    );
  };
};

// ── Prefetch helpers ────────────────────────────────────────────────────────

export const usePrefetchDocumentsList = () => {
  const qc = useQueryClient();
  const guildId = useActiveGuildId();
  return (params: ListDocumentsApiV1CGuildIdDocumentsGetParams) => {
    // The same query the list hook runs, so the row it warms is the row that
    // hook then finds in the cache.
    return qc.prefetchQuery({
      ...documents.listQuery(guildId, params),
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
    await setDocumentGrantsApiV1CGuildIdDocumentsDocumentIdGrantsPut(guildId, documentId, grants);
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
        newDocument = await copyDocumentApiV1CGuildIdDocumentsDocumentIdCopyPost(
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
        newDocument = await createDocumentApiV1CGuildIdDocumentsPost(guildId, payload);
      }

      // Auto-attach to project if specified
      if (project_id) {
        await relate(
          guildId,
          { type: SearchEntityType.project, id: project_id },
          { type: SearchEntityType.document, id: newDocument.id }
        );
      }

      return newDocument;
    },
    onSuccess: (...args) => {
      void invalidate(q.allDocuments());
      const projectId = args[1].project_id;
      if (projectId) {
        void invalidate(q.project(projectId));
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

      const uploadBody: BodyUploadDocumentFileApiV1CGuildIdDocumentsUploadPost = {
        file,
        name,
        initiative_id,
      };
      const newDocument = await uploadDocumentFileApiV1CGuildIdDocumentsUploadPost(
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
        await relate(
          guildId,
          { type: SearchEntityType.project, id: project_id },
          { type: SearchEntityType.document, id: newDocument.id }
        );
      }

      return newDocument;
    },
    onSuccess: (...args) => {
      void invalidate(q.allDocuments());
      const projectId = args[1].project_id;
      if (projectId) {
        void invalidate(q.project(projectId));
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
    queryKey: getListDocumentVersionsApiV1CGuildIdDocumentsDocumentIdVersionsGetQueryKey(
      guildId,
      documentId!
    ),
    queryFn: () =>
      listDocumentVersionsApiV1CGuildIdDocumentsDocumentIdVersionsGet(guildId, documentId!),
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
      const body: BodyUploadDocumentVersionApiV1CGuildIdDocumentsDocumentIdVersionsPost = { file };
      return uploadDocumentVersionApiV1CGuildIdDocumentsDocumentIdVersionsPost(
        guildId,
        documentId,
        body
      );
    },
    onSuccess: (...args) => {
      const documentId = args[1].documentId;
      void invalidate(q.documentVersions(documentId));
      // Mirror file fields on the document row changed — refresh detail + lists.
      void invalidate(q.document(documentId), q.allDocuments());
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
      await deleteDocumentVersionApiV1CGuildIdDocumentsDocumentIdVersionsVersionIdDelete(
        guildId,
        documentId,
        versionId
      );
    },
    onSuccess: (...args) => {
      const documentId = args[1].documentId;
      void invalidate(q.documentVersions(documentId), q.document(documentId), q.allDocuments());
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
      return updateDocumentApiV1CGuildIdDocumentsDocumentIdPatch(guildId, documentId, data);
    },
    onSuccess: (...args) => {
      const [updated] = args;
      queryClient.setQueryData(
        getReadDocumentApiV1CGuildIdDocumentsDocumentIdGetQueryKey(guildId, documentId),
        updated
      );
      // A save rewrites what the body refers to, which is what the other end's
      // "linked from" panel is reading.
      void invalidate(q.allDocuments(), q.relationships());
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
        documentIds.map((id) => deleteDocumentApiV1CGuildIdDocumentsDocumentIdDelete(guildId, id))
      );
    },
    onSuccess: (...args) => {
      const documentIds = args[1];
      if (!suppressSuccessToast) {
        toast.success(t("bulk.deleted", { count: documentIds.length }));
      }
      void invalidate(q.allDocuments());
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
          copyDocumentApiV1CGuildIdDocumentsDocumentIdCopyPost(guildId, doc.id, {
            target_initiative_id: doc.initiative_id,
            name: `${doc.name} (copy)`,
          })
        )
      );
      return results;
    },
    onSuccess: (...args) => {
      toast.success(t("bulk.duplicated", { count: args[0].length }));
      void invalidate(q.allDocuments());
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
        duplicateDocumentApiV1CGuildIdDocumentsDocumentIdDuplicatePost(guildId, documentId, {
          name,
        }),
      invalidate: () => invalidate(q.allDocuments()),
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
        copyDocumentApiV1CGuildIdDocumentsDocumentIdCopyPost(guildId, documentId, data),
      invalidate: () => invalidate(q.allDocuments()),
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
        generateSummaryApiV1CGuildIdDocumentsDocumentIdAiSummaryPost(guildId, documentId),
    },
    options
  );
