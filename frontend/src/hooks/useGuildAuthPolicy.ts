import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getListLoginProvidersApiV1AuthProvidersGetQueryKey,
  listLoginProvidersApiV1AuthProvidersGet,
} from "@/api/generated/auth/auth";
import {
  getGetGuildAuthPolicyApiV1GuildsGuildIdAuthPolicyGetQueryKey,
  getGuildAuthPolicyApiV1GuildsGuildIdAuthPolicyGet,
  setGuildAuthPolicyApiV1GuildsGuildIdAuthPolicyPut,
} from "@/api/generated/guilds/guilds";
import type {
  GuildAuthPolicyRead,
  GuildAuthPolicyUpdate,
  LoginProvidersResponse,
} from "@/api/generated/initiativeAPI.schemas";
import type { QueryOpts } from "@/types/query";

/** The sign-in providers the login page offers (non-secret metadata). */
export const useLoginProviders = (options?: QueryOpts<LoginProvidersResponse>) => {
  return useQuery<LoginProvidersResponse>({
    queryKey: getListLoginProvidersApiV1AuthProvidersGetQueryKey(),
    queryFn: () =>
      listLoginProvidersApiV1AuthProvidersGet() as unknown as Promise<LoginProvidersResponse>,
    staleTime: 60_000,
    ...options,
  });
};

/** The guild's sign-in requirement (guild admins only). */
export const useGuildAuthPolicy = (guildId: number, options?: QueryOpts<GuildAuthPolicyRead>) => {
  return useQuery<GuildAuthPolicyRead>({
    queryKey: getGetGuildAuthPolicyApiV1GuildsGuildIdAuthPolicyGetQueryKey(guildId),
    queryFn: () =>
      getGuildAuthPolicyApiV1GuildsGuildIdAuthPolicyGet(
        guildId
      ) as unknown as Promise<GuildAuthPolicyRead>,
    enabled: guildId > 0,
    ...options,
  });
};

/** Set the guild's sign-in requirement; refreshes the policy query on success. */
export const useUpdateGuildAuthPolicy = (guildId: number) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: GuildAuthPolicyUpdate) =>
      setGuildAuthPolicyApiV1GuildsGuildIdAuthPolicyPut(guildId, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: getGetGuildAuthPolicyApiV1GuildsGuildIdAuthPolicyGetQueryKey(guildId),
      });
    },
  });
};
