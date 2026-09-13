import { useQuery } from "@tanstack/react-query";

import type {
  UserEmailListResponse,
  UserEmailRead,
  VerificationSendResponse,
} from "@/api/generated/initiativeAPI.schemas";
import {
  addMyAddressApiV1UsersMeEmailsPost,
  getListMyAddressesApiV1UsersMeEmailsGetQueryKey,
  listMyAddressesApiV1UsersMeEmailsGet,
  makeMyAddressPrimaryApiV1UsersMeEmailsAddressIdPrimaryPut,
  removeMyAddressApiV1UsersMeEmailsAddressIdDelete,
} from "@/api/generated/users/users";
import { useApiMutation } from "@/hooks/useApiMutation";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";

// ── Query Keys ──────────────────────────────────────────────────────────────

export const ADDRESSES_QUERY_KEY = getListMyAddressesApiV1UsersMeEmailsGetQueryKey();

const refresh = () => queryClient.invalidateQueries({ queryKey: ADDRESSES_QUERY_KEY });

// ── Queries ─────────────────────────────────────────────────────────────────

/** Every address this account holds, proven or not. */
export const useMyAddresses = () =>
  useQuery<UserEmailListResponse>({
    queryKey: ADDRESSES_QUERY_KEY,
    queryFn: () => listMyAddressesApiV1UsersMeEmailsGet(),
  });

// ── Mutations ───────────────────────────────────────────────────────────────

/**
 * Start holding another address.
 *
 * The answer is the same whoever holds it already — a claim is recorded and
 * mail goes out, or nothing happens and mail goes to whoever proved it. So
 * there is one success message and it describes the letter, not the outcome.
 */
export const useAddAddress = (options?: MutationOpts<VerificationSendResponse, string>) =>
  useApiMutation<VerificationSendResponse, string>(
    {
      mutationFn: (email) => addMyAddressApiV1UsersMeEmailsPost({ email }),
      invalidate: refresh,
    },
    options
  );

export const useRemoveAddress = (options?: MutationOpts<void, number>) =>
  useApiMutation<void, number>(
    {
      mutationFn: (addressId) => removeMyAddressApiV1UsersMeEmailsAddressIdDelete(addressId),
      invalidate: refresh,
    },
    options
  );

export const useMakeAddressPrimary = (options?: MutationOpts<UserEmailRead, number>) =>
  useApiMutation<UserEmailRead, number>(
    {
      mutationFn: (addressId) =>
        makeMyAddressPrimaryApiV1UsersMeEmailsAddressIdPrimaryPut(addressId),
      invalidate: refresh,
    },
    options
  );

// ── Reading the list ────────────────────────────────────────────────────────

/**
 * Addresses minted for an account whose provider asserted none. They are
 * permanently unproven, nobody can receive mail at one, and their holder never
 * typed it — so this surface does not show them.
 */
const SYNTHETIC = "synthetic";

/** What the settings page lists: the account's own addresses, primary first. */
export const visibleAddresses = (data: UserEmailListResponse | undefined): UserEmailRead[] =>
  (data?.items ?? [])
    .filter((address) => address.source !== SYNTHETIC)
    .sort((a, b) => Number(b.is_primary) - Number(a.is_primary));

/**
 * Whether removing this address would leave the account with no proven one.
 *
 * The server refuses it either way; knowing here is what lets the button say
 * so before it is pressed rather than after.
 */
export const isOnlyProvenAddress = (address: UserEmailRead, addresses: UserEmailRead[]): boolean =>
  address.verified && addresses.filter((other) => other.verified).length === 1;
