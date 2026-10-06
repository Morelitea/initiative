import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import {
  createDocument,
  deleteDocumentVersion,
  duplicateDocument,
  generateSummary,
  getListDocumentVersionsQueryKey,
  getReadDocumentQueryKey,
  listDocumentVersions,
  setDocumentGrants,
  uploadDocumentFile,
  uploadDocumentVersion,
} from "@/api/generated/documents/documents";
import type {
  BodyUploadDocumentFile,
  BodyUploadDocumentVersion,
  DocumentCreate,
  DocumentFileVersionRead,
  DocumentRead,
  DocumentType,
  GenerateDocumentSummaryResponse,
  ResourceGrantSchema,
} from "@/api/generated/initiativeAPI.schemas";
import { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { relate } from "@/api/relationships";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── The standard hooks ──────────────────────────────────────────────────────
// Built in `toolHooks.ts` from the generated client; see there for the keys
// each one reads and the invalidation each one fires. A document's create is
// its own, and is written out below.

const documents = TOOL_HOOKS[Tool.document];
export const useDocumentsList = documents.useList;
export const useDocument = documents.useDetail;
export const useUpdateDocument = documents.useUpdate;
/**
 * Single-document delete — the shape every tool's delete hook takes, so the
 * shared settings page needs no per-tool adapter.
 */
export const useDeleteDocument = documents.useDelete;
export const useSetDocumentGrants = documents.useSetGrants;

// ── Cache helpers ───────────────────────────────────────────────────────────

export const useSetDocumentCache = () => {
  const qc = useQueryClient();
  const communityId = useActiveCommunityId();
  return (
    documentId: number,
    data: DocumentRead | ((prev: DocumentRead | undefined) => DocumentRead | undefined)
  ) => {
    qc.setQueryData<DocumentRead>(
      getReadDocumentQueryKey(communityId, documentId),
      typeof data === "function" ? data : () => data
    );
  };
};

// ── Mutations ───────────────────────────────────────────────────────────────

// Helper: apply a document's full sharing state via a follow-up grants PUT (for
// copy/upload paths where the create payload can't carry them). Returns 1 if the
// call failed, else 0.
const applyDocumentGrants = async (
  communityId: number,
  documentId: number,
  grants: ResourceGrantSchema[]
): Promise<number> => {
  if (grants.length === 0) return 0;
  try {
    await setDocumentGrants(communityId, documentId, grants);
    return 0;
  } catch {
    return 1;
  }
};

type CreateDocumentInput = {
  name: string;
  initiative_id: number;
  is_template?: boolean;
  template_id?: number;
  project_id?: number;
  /** Omit for native (text) documents; file uploads go through useUploadDocument instead. */
  document_type?: Exclude<DocumentType, "file">;
  /** Required for smart_link ({ url: "..." }). Optional/unused for other types. */
  content?: Record<string, unknown>;
  /** Full non-owner sharing state for the new document. */
  grants?: ResourceGrantSchema[];
};

export const useCreateDocument = (options?: MutationOpts<DocumentRead, CreateDocumentInput>) => {
  const { t } = useTranslation("documents");
  const communityId = useActiveCommunityId();
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
        newDocument = await duplicateDocument(communityId, template_id, {
          target_initiative_id: initiative_id,
          name,
        });
        // Template copy can't carry grants in payload — apply separately
        const failures = await applyDocumentGrants(communityId, newDocument.id, grants);
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
        newDocument = await createDocument(communityId, payload);
      }

      // Auto-attach to project if specified
      if (project_id) {
        await relate(
          communityId,
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

type UploadDocumentInput = {
  file: Blob;
  name: string;
  initiative_id: number;
  project_id?: number;
  /** Full non-owner sharing state for the uploaded document. */
  grants?: ResourceGrantSchema[];
};

export const useUploadDocument = (options?: MutationOpts<DocumentRead, UploadDocumentInput>) => {
  const { t } = useTranslation("documents");
  const communityId = useActiveCommunityId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: UploadDocumentInput) => {
      const { file, name, initiative_id, project_id, grants = [] } = data;

      const uploadBody: BodyUploadDocumentFile = {
        file,
        name,
        initiative_id,
      };
      const newDocument = await uploadDocumentFile(communityId, uploadBody);

      // Upload can't carry grants in payload — apply separately
      const failures = await applyDocumentGrants(communityId, newDocument.id, grants);
      if (failures > 0) {
        toast.warning(t("create.somePermissionsFailed"));
      }

      // Auto-attach to project if specified
      if (project_id) {
        await relate(
          communityId,
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
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<DocumentFileVersionRead[]>({
    queryKey: getListDocumentVersionsQueryKey(communityId, documentId!),
    queryFn: () => listDocumentVersions(communityId, documentId!),
    enabled: documentId !== null && Number.isFinite(documentId) && userEnabled,
    ...rest,
  });
};

export const useUploadDocumentVersion = (
  options?: MutationOpts<DocumentFileVersionRead, { documentId: number; file: Blob }>
) => {
  const { t } = useTranslation("documents");
  const communityId = useActiveCommunityId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ documentId, file }: { documentId: number; file: Blob }) => {
      const body: BodyUploadDocumentVersion = { file };
      return uploadDocumentVersion(communityId, documentId, body);
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
  const communityId = useActiveCommunityId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ documentId, versionId }: { documentId: number; versionId: number }) => {
      await deleteDocumentVersion(communityId, documentId, versionId);
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

// ── Document-scoped mutations ───────────────────────────────────────────────

export const useGenerateDocumentSummary = (
  documentId: number,
  options?: MutationOpts<GenerateDocumentSummaryResponse, void>
) =>
  useCommunityMutation<GenerateDocumentSummaryResponse, void>(
    {
      mutationFn: (communityId) => generateSummary(communityId, documentId),
    },
    options
  );
