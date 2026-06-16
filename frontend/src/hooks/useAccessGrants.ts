import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import {
  approveAccessGrantApiV1AccessGrantsGrantIdApprovePost,
  breakGlassAccessApiV1AccessGrantsBreakGlassPost,
  cancelAccessRequestApiV1AccessGrantsGrantIdDelete,
  createAccessRequestApiV1AccessGrantsPost,
  denyAccessGrantApiV1AccessGrantsGrantIdDenyPost,
  listAccessGrantsApiV1AccessGrantsGet,
  revokeAccessGrantApiV1AccessGrantsGrantIdRevokePost,
} from "@/api/generated/access-grants/access-grants";
import type {
  AccessGrantApprove,
  AccessGrantCreate,
  AccessGrantRead,
  BreakGlassCreate,
} from "@/api/generated/initiativeAPI.schemas";
import type { MutationOpts } from "@/types/mutation";

// Shared key prefix so any grant mutation refreshes every grant list.
const ACCESS_GRANTS_KEY = ["access-grants"] as const;

// Page size for the grant lists. The lists grow with users and usage, so they
// load a page at a time (newest-first) with a "Load more" affordance rather
// than fetching the whole history at once.
export const ACCESS_GRANTS_PAGE_SIZE = 25;

// A full page back means there may be more; a short page is the end.
const nextOffset = (
  lastPage: AccessGrantRead[],
  allPages: AccessGrantRead[][]
): number | undefined =>
  lastPage.length === ACCESS_GRANTS_PAGE_SIZE
    ? allPages.length * ACCESS_GRANTS_PAGE_SIZE
    : undefined;

/** Flatten the loaded pages of an access-grants infinite query into one array. */
export const flattenGrants = (pages: AccessGrantRead[][] | undefined): AccessGrantRead[] =>
  pages?.flat() ?? [];

function useInvalidateAccessGrants() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ACCESS_GRANTS_KEY });
}

/** The current user's own access requests, paged newest-first. */
export const useMyAccessGrants = () =>
  useInfiniteQuery({
    queryKey: [...ACCESS_GRANTS_KEY, "mine"],
    queryFn: ({ pageParam }) =>
      listAccessGrantsApiV1AccessGrantsGet({
        mine: true,
        limit: ACCESS_GRANTS_PAGE_SIZE,
        offset: pageParam,
      }) as unknown as Promise<AccessGrantRead[]>,
    initialPageParam: 0,
    getNextPageParam: nextOffset,
  });

/**
 * The full queue filtered by status — requires access.read (approvers). Pass
 * ``live: true`` to keep only grants still within their window (so server-side
 * paging of the active list is accurate).
 */
export const useAccessGrantQueue = (status: string | undefined, opts?: { live?: boolean }) =>
  useInfiniteQuery({
    queryKey: [...ACCESS_GRANTS_KEY, "queue", status ?? "all", opts?.live ? "live" : "all"],
    queryFn: ({ pageParam }) =>
      listAccessGrantsApiV1AccessGrantsGet({
        mine: false,
        status,
        live: opts?.live,
        limit: ACCESS_GRANTS_PAGE_SIZE,
        offset: pageParam,
      }) as unknown as Promise<AccessGrantRead[]>,
    initialPageParam: 0,
    getNextPageParam: nextOffset,
  });

export const useCreateAccessRequest = (
  options?: MutationOpts<AccessGrantRead, AccessGrantCreate>
) => {
  const invalidate = useInvalidateAccessGrants();
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (payload: AccessGrantCreate) =>
      createAccessRequestApiV1AccessGrantsPost(payload) as unknown as Promise<AccessGrantRead>,
    onSuccess: (...args) => {
      void invalidate();
      onSuccess?.(...args);
    },
  });
};

export const useApproveAccessGrant = (
  options?: MutationOpts<AccessGrantRead, { grantId: number; payload?: AccessGrantApprove }>
) => {
  const invalidate = useInvalidateAccessGrants();
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: ({ grantId, payload }: { grantId: number; payload?: AccessGrantApprove }) =>
      approveAccessGrantApiV1AccessGrantsGrantIdApprovePost(
        grantId,
        payload ?? {}
      ) as unknown as Promise<AccessGrantRead>,
    onSuccess: (...args) => {
      void invalidate();
      onSuccess?.(...args);
    },
  });
};

export const useDenyAccessGrant = (options?: MutationOpts<AccessGrantRead, number>) => {
  const invalidate = useInvalidateAccessGrants();
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (grantId: number) =>
      denyAccessGrantApiV1AccessGrantsGrantIdDenyPost(
        grantId
      ) as unknown as Promise<AccessGrantRead>,
    onSuccess: (...args) => {
      void invalidate();
      onSuccess?.(...args);
    },
  });
};

export const useRevokeAccessGrant = (options?: MutationOpts<AccessGrantRead, number>) => {
  const invalidate = useInvalidateAccessGrants();
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (grantId: number) =>
      revokeAccessGrantApiV1AccessGrantsGrantIdRevokePost(
        grantId
      ) as unknown as Promise<AccessGrantRead>,
    onSuccess: (...args) => {
      void invalidate();
      onSuccess?.(...args);
    },
  });
};

/**
 * Self-issue a break-glass grant (requires data.bypass). Unlike a request, this
 * is created AND approved in one step, so it's live immediately — the holder can
 * then enter the guild via its ``/g/{guild_id}`` path until it expires.
 */
export const useBreakGlass = (options?: MutationOpts<AccessGrantRead, BreakGlassCreate>) => {
  const invalidate = useInvalidateAccessGrants();
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (payload: BreakGlassCreate) =>
      breakGlassAccessApiV1AccessGrantsBreakGlassPost(
        payload
      ) as unknown as Promise<AccessGrantRead>,
    onSuccess: (...args) => {
      void invalidate();
      onSuccess?.(...args);
    },
  });
};

export const useCancelAccessRequest = (options?: MutationOpts<void, number>) => {
  const invalidate = useInvalidateAccessGrants();
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (grantId: number) =>
      cancelAccessRequestApiV1AccessGrantsGrantIdDelete(grantId) as unknown as Promise<void>,
    onSuccess: (...args) => {
      void invalidate();
      onSuccess?.(...args);
    },
  });
};
