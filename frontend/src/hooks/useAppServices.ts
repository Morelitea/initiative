import { useQuery } from "@tanstack/react-query";

import {
  connectAppServiceApiV1AppServicesRegistrationIdConnectPost,
  createAppServiceApiV1AppServicesPost,
  deleteAppServiceApiV1AppServicesRegistrationIdDelete,
  getListAppServicesApiV1AppServicesGetQueryKey,
  listAppServicesApiV1AppServicesGet,
  readAppServiceKeysApiV1AppServicesRegistrationIdConnectGet,
  updateAppServiceApiV1AppServicesRegistrationIdPatch,
} from "@/api/generated/app-services/app-services";
import type {
  AppServicePublishedKey,
  AppServiceRegistrationCreate,
  AppServiceRegistrationRead,
  AppServiceRegistrationUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** Every app service this deployment has wired up (`apps.manage`). */
export const useAppServices = (options?: QueryOpts<AppServiceRegistrationRead[]>) =>
  useQuery<AppServiceRegistrationRead[]>({
    queryKey: getListAppServicesApiV1AppServicesGetQueryKey(),
    queryFn: () => listAppServicesApiV1AppServicesGet(),
    ...options,
  });

export const useCreateAppService = (
  options?: MutationOpts<AppServiceRegistrationRead, AppServiceRegistrationCreate>
) =>
  useApiMutation<AppServiceRegistrationRead, AppServiceRegistrationCreate>(
    {
      mutationFn: (data) => createAppServiceApiV1AppServicesPost(data),
      invalidate: () => invalidate(q.appServices()),
    },
    options
  );

export interface UpdateAppServiceVariables {
  registrationId: number;
  data: AppServiceRegistrationUpdate;
}

export const useUpdateAppService = (
  options?: MutationOpts<AppServiceRegistrationRead, UpdateAppServiceVariables>
) =>
  useApiMutation<AppServiceRegistrationRead, UpdateAppServiceVariables>(
    {
      mutationFn: ({ registrationId, data }) =>
        updateAppServiceApiV1AppServicesRegistrationIdPatch(registrationId, data),
      invalidate: () => invalidate(q.appServices()),
    },
    options
  );

export const useDeleteAppService = (options?: MutationOpts<void, number>) =>
  useApiMutation<void, number>(
    {
      mutationFn: (registrationId) =>
        deleteAppServiceApiV1AppServicesRegistrationIdDelete(registrationId),
      invalidate: () => invalidate(q.appServices()),
    },
    options
  );

/**
 * Read the keys an app serves at its base URL, each with its fingerprint. A
 * mutation because it runs when the operator presses Connect, and stores
 * nothing.
 */
export const useAppServiceKeys = (options?: MutationOpts<AppServicePublishedKey[], number>) =>
  useApiMutation<AppServicePublishedKey[], number>(
    {
      mutationFn: (registrationId) =>
        readAppServiceKeysApiV1AppServicesRegistrationIdConnectGet(registrationId),
    },
    options
  );

export interface ConnectAppServiceVariables {
  registrationId: number;
  /** The keys the operator was shown and confirmed, kid and fingerprint. */
  keys: AppServicePublishedKey[];
}

/** Pin the key set the app serves, when it still holds exactly the confirmed keys. */
export const useConnectAppService = (
  options?: MutationOpts<AppServiceRegistrationRead, ConnectAppServiceVariables>
) =>
  useApiMutation<AppServiceRegistrationRead, ConnectAppServiceVariables>(
    {
      mutationFn: ({ registrationId, keys }) =>
        connectAppServiceApiV1AppServicesRegistrationIdConnectPost(registrationId, {
          keys,
        }),
      invalidate: () => invalidate(q.appServices()),
    },
    options
  );
