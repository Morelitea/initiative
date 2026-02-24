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
  getBacklinksApiV1DocumentsDocumentIdBacklinksGet,
  getGetBacklinksApiV1DocumentsDocumentIdBacklinksGetQueryKey,
  createDocumentApiV1DocumentsPost,
  uploadDocumentFileApiV1DocumentsUploadPost,
  deleteDocumentApiV1DocumentsDocumentIdDelete,
  copyDocumentApiV1DocumentsDocumentIdCopyPost,
  updateDocumentApiV1DocumentsDocumentIdPatch,
  duplicateDocumentApiV1DocumentsDocumentIdDuplicatePost,
  generateSummaryApiV1DocumentsDocumentIdAiSummaryPost,
  addDocumentMemberApiV1DocumentsDocumentIdMembersPost,
  updateDocumentMemberApiV1DocumentsDocumentIdMembersUserIdPatch,
  removeDocumentMemberApiV1DocumentsDocumentIdMembersUserIdDelete,
  addDocumentMembersBulkApiV1DocumentsDocumentIdMembersBulkPost,
  removeDocumentMembersBulkApiV1DocumentsDocumentIdMembersBulkDeletePost,
  addDocumentRolePermissionApiV1DocumentsDocumentIdRolePermissionsPost,
  updateDocumentRolePermissionApiV1DocumentsDocumentIdRolePermissionsRoleIdPatch,
  removeDocumentRolePermissionApiV1DocumentsDocumentIdRolePermissionsRoleIdDelete,
} from "@/api/generated/documents/documents";
import { attachProjectDocumentApiV1ProjectsProjectIdDocumentsDocumentIdPost } from "@/api/generated/projects/projects";
import { invalidateAllDocuments, invalidateDocument, invalidateProject } from "@/api/query-keys";
import type {
  DocumentCountsResponse,
  DocumentCreate,
  DocumentListResponse,
  DocumentRead,
  DocumentPermissionCreate,
  DocumentPermissionLevel,
  DocumentPermissionBulkCreate,
  DocumentPermissionBulkDelete,
  DocumentRolePermissionCreate,
  GenerateDocumentSummaryResponse,
} from "@/api/generated/initiativeAPI.schemas";
import type {
  ListDocumentsApiV1DocumentsGetParams,
  GetDocumentCountsApiV1DocumentsCountsGetParams,
  BodyUploadDocumentFileApiV1DocumentsUploadPost,
  DocumentUpdate,
  DocumentBacklink,
  DocumentSummary,
} from "@/api/generated/initiativeAPI.schemas";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

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
    // Distinct key from useDocumentsList({ page_size: 0 }) — the extra
    // "items" segment prevents cache collisions with the paginated variant.
    queryKey: [...getListDocumentsApiV1DocumentsGetQueryKey({ page_size: 0 }), "items"],
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

// Helper: apply role + user permissions via follow-up API calls (for copy/upload paths
// where the create payload can't carry them). Returns count of failed permission calls.
const applyDocumentPermissions = async (
  documentId: number,
  roleGrants: DocumentRolePermissionCreate[],
  userGrants: DocumentPermissionCreate[]
): Promise<number> => {
  let failures = 0;
  for (const rg of roleGrants) {
    try {
      await addDocumentRolePermissionApiV1DocumentsDocumentIdRolePermissionsPost(documentId, {
        initiative_role_id: rg.initiative_role_id,
        level: rg.level,
      });
    } catch {
      failures++;
    }
  }
  // Batch user grants by level to use bulk endpoint
  const byLevel = new Map<string, number[]>();
  for (const ug of userGrants) {
    const level = ug.level ?? "read";
    const arr = byLevel.get(level) ?? [];
    arr.push(ug.user_id);
    byLevel.set(level, arr);
  }
  for (const [level, userIds] of byLevel) {
    try {
      await addDocumentMembersBulkApiV1DocumentsDocumentIdMembersBulkPost(documentId, {
        user_ids: userIds,
        level: level as DocumentPermissionLevel,
      });
    } catch {
      failures++;
    }
  }
  return failures;
};

export type CreateDocumentInput = {
  title: string;
  initiative_id: number;
  is_template?: boolean;
  template_id?: number;
  project_id?: number;
  role_grants?: DocumentRolePermissionCreate[];
  user_grants?: DocumentPermissionCreate[];
};

export const useCreateDocument = (options?: MutationOpts<DocumentRead, CreateDocumentInput>) => {
  const { t } = useTranslation("documents");
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
        role_grants = [],
        user_grants = [],
      } = data;

      let newDocument: DocumentRead;

      if (template_id) {
        // Copy from template
        newDocument = (await copyDocumentApiV1DocumentsDocumentIdCopyPost(template_id, {
          target_initiative_id: initiative_id,
          title,
        })) as unknown as DocumentRead;
        // Template copy can't carry permissions in payload — apply separately
        const failures = await applyDocumentPermissions(newDocument.id, role_grants, user_grants);
        if (failures > 0) {
          toast.warning(t("create.somePermissionsFailed"));
        }
      } else {
        // Direct create — pass permissions in the payload (backend handles them)
        const payload: DocumentCreate = {
          title,
          initiative_id,
          is_template: is_template ?? false,
          ...(role_grants.length > 0 ? { role_permissions: role_grants } : {}),
          ...(user_grants.length > 0 ? { user_permissions: user_grants } : {}),
        };
        newDocument = (await createDocumentApiV1DocumentsPost(payload)) as unknown as DocumentRead;
      }

      // Auto-attach to project if specified
      if (project_id) {
        await attachProjectDocumentApiV1ProjectsProjectIdDocumentsDocumentIdPost(
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
      const message = args[0] instanceof Error ? args[0].message : t("create.createError");
      toast.error(message);
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
  role_grants?: DocumentRolePermissionCreate[];
  user_grants?: DocumentPermissionCreate[];
};

export const useUploadDocument = (options?: MutationOpts<DocumentRead, UploadDocumentInput>) => {
  const { t } = useTranslation("documents");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: UploadDocumentInput) => {
      const { file, title, initiative_id, project_id, role_grants = [], user_grants = [] } = data;

      const uploadBody: BodyUploadDocumentFileApiV1DocumentsUploadPost = {
        file,
        title,
        initiative_id,
      };
      const newDocument = (await uploadDocumentFileApiV1DocumentsUploadPost(
        uploadBody
      )) as unknown as DocumentRead;

      // Upload can't carry permissions in payload — apply separately
      const failures = await applyDocumentPermissions(newDocument.id, role_grants, user_grants);
      if (failures > 0) {
        toast.warning(t("create.somePermissionsFailed"));
      }

      // Auto-attach to project if specified
      if (project_id) {
        await attachProjectDocumentApiV1ProjectsProjectIdDocumentsDocumentIdPost(
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
      const message = args[0] instanceof Error ? args[0].message : t("create.uploadError");
      toast.error(message);
      onError?.(...args);
    },
    onSettled,
  });
};

export const useUpdateDocument = (
  options?: MutationOpts<DocumentRead, { documentId: number; data: DocumentUpdate }>
) => {
  const { t } = useTranslation("documents");
  const queryClient = useQueryClient();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ documentId, data }: { documentId: number; data: DocumentUpdate }) => {
      return updateDocumentApiV1DocumentsDocumentIdPatch(
        documentId,
        data
      ) as unknown as Promise<DocumentRead>;
    },
    onSuccess: (...args) => {
      const [updated, vars] = args;
      queryClient.setQueryData(
        getReadDocumentApiV1DocumentsDocumentIdGetQueryKey(vars.documentId),
        updated
      );
      void invalidateAllDocuments();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      const message = args[0] instanceof Error ? args[0].message : t("detail.saveError");
      toast.error(message);
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteDocument = (options?: MutationOpts<void, number[]>) => {
  const { t } = useTranslation("documents");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (documentIds: number[]) => {
      await Promise.all(documentIds.map((id) => deleteDocumentApiV1DocumentsDocumentIdDelete(id)));
    },
    onSuccess: (...args) => {
      const documentIds = args[1];
      toast.success(t("bulk.deleted", { count: documentIds.length }));
      void invalidateAllDocuments();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      const message = args[0] instanceof Error ? args[0].message : t("bulk.deleteError");
      toast.error(message);
      onError?.(...args);
    },
    onSettled,
  });
};

export const useCopyDocument = (
  options?: MutationOpts<DocumentRead[], { id: number; initiative_id: number; title: string }[]>
) => {
  const { t } = useTranslation("documents");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
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
    onSuccess: (...args) => {
      toast.success(t("bulk.duplicated", { count: args[0].length }));
      void invalidateAllDocuments();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      const message = args[0] instanceof Error ? args[0].message : t("bulk.duplicateError");
      toast.error(message);
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ title }: { title: string }) => {
      return duplicateDocumentApiV1DocumentsDocumentIdDuplicatePost(documentId, {
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: { target_initiative_id: number; title: string }) => {
      return copyDocumentApiV1DocumentsDocumentIdCopyPost(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async () => {
      return generateSummaryApiV1DocumentsDocumentIdAiSummaryPost(
        documentId
      ) as unknown as Promise<GenerateDocumentSummaryResponse>;
    },
    onSuccess,
    onError,
    onSettled,
  });
};

export const useAddDocumentMember = (
  documentId: number,
  options?: MutationOpts<void, { userId: number; level: DocumentPermissionLevel }>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ userId, level }: { userId: number; level: DocumentPermissionLevel }) => {
      await addDocumentMemberApiV1DocumentsDocumentIdMembersPost(documentId, {
        user_id: userId,
        level,
      });
    },
    onSuccess: (...args) => {
      void invalidateDocument(documentId);
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useUpdateDocumentMember = (
  documentId: number,
  options?: MutationOpts<void, { userId: number; level: DocumentPermissionLevel }>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ userId, level }: { userId: number; level: DocumentPermissionLevel }) => {
      await updateDocumentMemberApiV1DocumentsDocumentIdMembersUserIdPatch(documentId, userId, {
        level,
      });
    },
    onSuccess: (...args) => {
      void invalidateDocument(documentId);
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useRemoveDocumentMember = (
  documentId: number,
  options?: MutationOpts<void, number>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (userId: number) => {
      await removeDocumentMemberApiV1DocumentsDocumentIdMembersUserIdDelete(documentId, userId);
    },
    onSuccess: (...args) => {
      void invalidateDocument(documentId);
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useAddDocumentMembersBulk = (
  documentId: number,
  options?: MutationOpts<void, DocumentPermissionBulkCreate>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: DocumentPermissionBulkCreate) => {
      await addDocumentMembersBulkApiV1DocumentsDocumentIdMembersBulkPost(documentId, data);
    },
    onSuccess: (...args) => {
      void invalidateDocument(documentId);
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useRemoveDocumentMembersBulk = (
  documentId: number,
  options?: MutationOpts<void, DocumentPermissionBulkDelete>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: DocumentPermissionBulkDelete) => {
      await removeDocumentMembersBulkApiV1DocumentsDocumentIdMembersBulkDeletePost(
        documentId,
        data
      );
    },
    onSuccess: (...args) => {
      void invalidateDocument(documentId);
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useAddDocumentRolePermission = (
  documentId: number,
  options?: MutationOpts<void, { roleId: number; level: "read" | "write" }>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ roleId, level }: { roleId: number; level: "read" | "write" }) => {
      await addDocumentRolePermissionApiV1DocumentsDocumentIdRolePermissionsPost(documentId, {
        initiative_role_id: roleId,
        level,
      });
    },
    onSuccess: (...args) => {
      void invalidateDocument(documentId);
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useUpdateDocumentRolePermission = (
  documentId: number,
  options?: MutationOpts<void, { roleId: number; level: "read" | "write" }>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ roleId, level }: { roleId: number; level: "read" | "write" }) => {
      await updateDocumentRolePermissionApiV1DocumentsDocumentIdRolePermissionsRoleIdPatch(
        documentId,
        roleId,
        { level }
      );
    },
    onSuccess: (...args) => {
      void invalidateDocument(documentId);
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useRemoveDocumentRolePermission = (
  documentId: number,
  options?: MutationOpts<void, number>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (roleId: number) => {
      await removeDocumentRolePermissionApiV1DocumentsDocumentIdRolePermissionsRoleIdDelete(
        documentId,
        roleId
      );
    },
    onSuccess: (...args) => {
      void invalidateDocument(documentId);
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};
