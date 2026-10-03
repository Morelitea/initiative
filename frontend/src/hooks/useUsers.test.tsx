/**
 * A member's API access is a switch on the roster, so a saved answer has to be
 * what the roster pages already loaded read, not only what their refetch will.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { buildUserCommunityMember } from "@/__tests__/factories";
import type { UserCommunityMemberListResponse } from "@/api/generated/initiativeAPI.schemas";
import { getListUsersQueryKey } from "@/api/generated/users/users";
import { useSetMemberApiAccess } from "@/hooks/useUsers";

vi.mock("@/api/generated/communities/communities", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  setMemberApiAccess: vi.fn().mockResolvedValue(undefined),
}));

const page = (
  ...items: ReturnType<typeof buildUserCommunityMember>[]
): UserCommunityMemberListResponse => ({
  items,
  total_count: items.length,
  page: 1,
  page_size: 20,
  has_next: false,
  has_prev: false,
});

describe("useSetMemberApiAccess", () => {
  it("writes the saved answer into every roster page already loaded", async () => {
    const client = new QueryClient();
    const member = buildUserCommunityMember({ api_keys_allowed: true });
    const keys = [
      getListUsersQueryKey(1, { page: 1, page_size: 20 }),
      getListUsersQueryKey(1, { search: member.username, page: 1, page_size: 20 }),
    ];
    for (const key of keys) client.setQueryData(key, page(member));

    const { result } = renderHook(() => useSetMemberApiAccess(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    });
    await act(() =>
      result.current.mutateAsync({ communityId: 1, userId: member.id, allowed: false })
    );

    for (const key of keys) {
      expect(
        client.getQueryData<UserCommunityMemberListResponse>(key)?.items[0].api_keys_allowed
      ).toBe(false);
    }
  });
});
