/**
 * The marketplace registry, as the platform owner manages it: whether this
 * server follows it, how the last refresh went, "refresh now", and uploading a
 * registry bundle for a server that cannot reach it.
 *
 * Every write changes what the catalog holds, so each one refreshes the status
 * and every community's marketplace listings.
 */

import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  RegistryRefreshRead,
  RegistrySettings,
  RegistryStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getReadRegistryStatusApiV1MarketplaceRegistryStatusGetQueryKey,
  readRegistryStatusApiV1MarketplaceRegistryStatusGet,
  refreshRegistryNowApiV1MarketplaceRegistryRefreshPost,
  updateRegistrySettingsApiV1MarketplaceRegistrySettingsPut,
  uploadRegistryBundleApiV1MarketplaceRegistryBundlePost,
} from "@/api/generated/marketplace/marketplace";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

const invalidateRegistry = (queryClient: QueryClient) => {
  void queryClient.invalidateQueries({
    queryKey: getReadRegistryStatusApiV1MarketplaceRegistryStatusGetQueryKey(),
  });
  // The shelf is keyed per community, so every community's copy is dropped.
  void queryClient.invalidateQueries({
    predicate: (query) =>
      typeof query.queryKey[0] === "string" && query.queryKey[0].includes("/marketplace/"),
  });
};

export const useRegistryStatus = (options?: QueryOpts<RegistryStatusRead>) =>
  useQuery<RegistryStatusRead>({
    queryKey: getReadRegistryStatusApiV1MarketplaceRegistryStatusGetQueryKey(),
    queryFn: () => readRegistryStatusApiV1MarketplaceRegistryStatusGet(),
    ...options,
  });

export const useUpdateRegistrySettings = (
  options?: MutationOpts<RegistrySettings, RegistrySettings>
) => {
  const queryClient = useQueryClient();
  const { onSuccess, ...rest } = options ?? {};
  return useMutation<RegistrySettings, Error, RegistrySettings>({
    ...rest,
    mutationFn: (data) => updateRegistrySettingsApiV1MarketplaceRegistrySettingsPut(data),
    onSuccess: (...args) => {
      invalidateRegistry(queryClient);
      onSuccess?.(...args);
    },
  });
};

export const useRefreshRegistry = (options?: MutationOpts<RegistryRefreshRead, void>) => {
  const queryClient = useQueryClient();
  const { onSuccess, onError, ...rest } = options ?? {};
  return useMutation<RegistryRefreshRead, Error, void>({
    ...rest,
    mutationFn: () => refreshRegistryNowApiV1MarketplaceRegistryRefreshPost(),
    onSuccess: (...args) => {
      invalidateRegistry(queryClient);
      onSuccess?.(...args);
    },
    // A refusal is recorded on the status too, so it is refetched either way.
    onError: (...args) => {
      invalidateRegistry(queryClient);
      onError?.(...args);
    },
  });
};

export const useUploadRegistryBundle = (options?: MutationOpts<RegistryRefreshRead, File>) => {
  const queryClient = useQueryClient();
  const { onSuccess, onError, ...rest } = options ?? {};
  return useMutation<RegistryRefreshRead, Error, File>({
    ...rest,
    mutationFn: (file) => uploadRegistryBundleApiV1MarketplaceRegistryBundlePost({ file }),
    onSuccess: (...args) => {
      invalidateRegistry(queryClient);
      onSuccess?.(...args);
    },
    onError: (...args) => {
      invalidateRegistry(queryClient);
      onError?.(...args);
    },
  });
};
