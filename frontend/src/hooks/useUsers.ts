import { useQuery, type UseQueryOptions } from "@tanstack/react-query";

import {
  listUsersApiV1UsersGet,
  getListUsersApiV1UsersGetQueryKey,
} from "@/api/generated/users/users";
import type { UserGuildMember } from "@/api/generated/initiativeAPI.schemas";

type QueryOpts<T> = Omit<UseQueryOptions<T>, "queryKey" | "queryFn">;

// ── Queries ─────────────────────────────────────────────────────────────────

export const useUsers = (options?: QueryOpts<UserGuildMember[]>) => {
  return useQuery<UserGuildMember[]>({
    queryKey: getListUsersApiV1UsersGetQueryKey(),
    queryFn: () => listUsersApiV1UsersGet() as unknown as Promise<UserGuildMember[]>,
    ...options,
  });
};
