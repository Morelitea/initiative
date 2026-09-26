import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  approveAccessGrantApiV1AccessGrantsGrantIdApprovePost,
  breakGlassAccessApiV1AccessGrantsBreakGlassPost,
  breakGlassRequirementsApiV1AccessGrantsBreakGlassGet,
  cancelAccessRequestApiV1AccessGrantsGrantIdDelete,
  createAccessRequestApiV1AccessGrantsPost,
  denyAccessGrantApiV1AccessGrantsGrantIdDenyPost,
  getBreakGlassRequirementsApiV1AccessGrantsBreakGlassGetQueryKey,
  getListAccessGrantQueueApiV1AccessGrantsQueueGetQueryKey,
  getListAccessGrantsApiV1AccessGrantsGetQueryKey,
  getReadAccessGrantLimitsApiV1AccessGrantsLimitsGetQueryKey,
  listAccessGrantQueueApiV1AccessGrantsQueueGet,
  listAccessGrantsApiV1AccessGrantsGet,
  readAccessGrantLimitsApiV1AccessGrantsLimitsGet,
  revokeAccessGrantApiV1AccessGrantsGrantIdRevokePost,
} from "@/api/generated/access-grants/access-grants";
import type {
  AccessGrantApprove,
  AccessGrantCreate,
  AccessGrantLimits,
  AccessGrantRead,
  BreakGlassCreate,
  BreakGlassRequirements,
} from "@/api/generated/initiativeAPI.schemas";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

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

/** Any grant mutation refreshes both lists, every filter of each. */
function useInvalidateAccessGrants() {
  const qc = useQueryClient();
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: getListAccessGrantsApiV1AccessGrantsGetQueryKey() }),
      qc.invalidateQueries({
        queryKey: getListAccessGrantQueueApiV1AccessGrantsQueueGetQueryKey(),
      }),
    ]);
}

/** The current user's own access requests, paged newest-first. */
export const useMyAccessGrants = () =>
  useInfiniteQuery({
    queryKey: getListAccessGrantsApiV1AccessGrantsGetQueryKey(),
    queryFn: ({ pageParam }) =>
      listAccessGrantsApiV1AccessGrantsGet({
        limit: ACCESS_GRANTS_PAGE_SIZE,
        offset: pageParam,
      }),
    initialPageParam: 0,
    getNextPageParam: nextOffset,
  });

/**
 * The full queue filtered by status — requires access.approve (approvers). Pass
 * ``live: true`` to keep only grants still within their window (so server-side
 * paging of the active list is accurate).
 */
export const useAccessGrantQueue = (status: string | undefined, opts?: { live?: boolean }) =>
  useInfiniteQuery({
    queryKey: getListAccessGrantQueueApiV1AccessGrantsQueueGetQueryKey({
      status,
      live: opts?.live,
    }),
    queryFn: ({ pageParam }) =>
      listAccessGrantQueueApiV1AccessGrantsQueueGet({
        status,
        live: opts?.live,
        limit: ACCESS_GRANTS_PAGE_SIZE,
        offset: pageParam,
      }),
    initialPageParam: 0,
    getNextPageParam: nextOffset,
  });

/**
 * The longest window the caller may request, as this deployment configures it
 * — requires access.request. The request form offers durations up to it.
 */
export const useAccessGrantLimits = (options?: { enabled?: boolean }) =>
  useQuery<AccessGrantLimits>({
    queryKey: getReadAccessGrantLimitsApiV1AccessGrantsLimitsGetQueryKey(),
    queryFn: () => readAccessGrantLimitsApiV1AccessGrantsLimitsGet(),
    enabled: options?.enabled ?? true,
  });

export const useCreateAccessRequest = (
  options?: MutationOpts<AccessGrantRead, AccessGrantCreate>
) => {
  const invalidate = useInvalidateAccessGrants();
  return useApiMutation<AccessGrantRead, AccessGrantCreate>(
    {
      mutationFn: (payload) => createAccessRequestApiV1AccessGrantsPost(payload),
      invalidate: () => invalidate(),
    },
    options
  );
};

export const useApproveAccessGrant = (
  options?: MutationOpts<AccessGrantRead, { grantId: number; payload?: AccessGrantApprove }>
) => {
  const invalidate = useInvalidateAccessGrants();
  return useApiMutation<AccessGrantRead, { grantId: number; payload?: AccessGrantApprove }>(
    {
      mutationFn: ({ grantId, payload }) =>
        approveAccessGrantApiV1AccessGrantsGrantIdApprovePost(grantId, payload ?? {}),
      invalidate: () => invalidate(),
    },
    options
  );
};

export const useDenyAccessGrant = (options?: MutationOpts<AccessGrantRead, number>) => {
  const invalidate = useInvalidateAccessGrants();
  return useApiMutation<AccessGrantRead, number>(
    {
      mutationFn: (grantId) => denyAccessGrantApiV1AccessGrantsGrantIdDenyPost(grantId),
      invalidate: () => invalidate(),
    },
    options
  );
};

export const useRevokeAccessGrant = (options?: MutationOpts<AccessGrantRead, number>) => {
  const invalidate = useInvalidateAccessGrants();
  return useApiMutation<AccessGrantRead, number>(
    {
      mutationFn: (grantId) => revokeAccessGrantApiV1AccessGrantsGrantIdRevokePost(grantId),
      invalidate: () => invalidate(),
    },
    options
  );
};

/**
 * What a break-glass request will be asked for, read before the form is filled
 * in. Breaking glass carries the account's own second factor once any
 * data.bypass holder has one, which is a property of the platform rather than
 * of the caller — so the form asks rather than inferring it.
 */
export const useBreakGlassRequirements = () =>
  useQuery<BreakGlassRequirements>({
    queryKey: getBreakGlassRequirementsApiV1AccessGrantsBreakGlassGetQueryKey(),
    queryFn: () => breakGlassRequirementsApiV1AccessGrantsBreakGlassGet(),
    // Somebody else enrolling changes this answer, and nothing here would know
    // to invalidate it — so it is read fresh on mount rather than inheriting
    // the shared staleness window.
    staleTime: 0,
    refetchOnMount: "always",
  });

/**
 * Self-issue a break-glass grant (requires data.bypass). Unlike a request, this
 * is created AND approved in one step, so it's live immediately — the holder can
 * then enter the guild via its ``/c/{guild_id}`` path until it expires.
 */
export const useBreakGlass = (options?: MutationOpts<AccessGrantRead, BreakGlassCreate>) => {
  const invalidate = useInvalidateAccessGrants();
  return useApiMutation<AccessGrantRead, BreakGlassCreate>(
    {
      mutationFn: (payload) => breakGlassAccessApiV1AccessGrantsBreakGlassPost(payload),
      invalidate: () => invalidate(),
    },
    options
  );
};

export const useCancelAccessRequest = (options?: MutationOpts<void, number>) => {
  const invalidate = useInvalidateAccessGrants();
  return useApiMutation<void, number>(
    {
      mutationFn: (grantId) => cancelAccessRequestApiV1AccessGrantsGrantIdDelete(grantId),
      invalidate: () => invalidate(),
    },
    options
  );
};
