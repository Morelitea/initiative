import { useQuery } from "@tanstack/react-query";

import {
  createAppServiceApiV1AppServicesPost,
  deleteAppServiceApiV1AppServicesRegistrationIdDelete,
  getListAppServicesApiV1AppServicesGetQueryKey,
  listAppServicesApiV1AppServicesGet,
  updateAppServiceApiV1AppServicesRegistrationIdPatch,
  verifyAppServiceApiV1AppServicesRegistrationIdVerifyPost,
} from "@/api/generated/app-services/app-services";
import type {
  AppServiceRegistrationCreate,
  AppServiceRegistrationRead,
  AppServiceRegistrationUpdate,
  AppServiceVerifyRequest,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidateAppServices } from "@/api/query-keys";
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
      invalidate: () => invalidateAppServices(),
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
      invalidate: () => invalidateAppServices(),
    },
    options
  );

export const useDeleteAppService = (options?: MutationOpts<void, number>) =>
  useApiMutation<void, number>(
    {
      mutationFn: (registrationId) =>
        deleteAppServiceApiV1AppServicesRegistrationIdDelete(registrationId),
      invalidate: () => invalidateAppServices(),
    },
    options
  );

export interface VerifyAppServiceVariables {
  registrationId: number;
  data?: AppServiceVerifyRequest;
}

/**
 * Re-run the handshake.
 *
 * The row records the attempt's outcome before any refusal is raised, so a
 * failed verify still moved `status` — the list is invalidated on error as
 * well as on success, or the badge would keep showing the previous state.
 */
export const useVerifyAppService = (
  options?: MutationOpts<AppServiceRegistrationRead, VerifyAppServiceVariables>
) => {
  const { onError, ...rest } = options ?? {};

  return useApiMutation<AppServiceRegistrationRead, VerifyAppServiceVariables>(
    {
      mutationFn: ({ registrationId, data }) =>
        verifyAppServiceApiV1AppServicesRegistrationIdVerifyPost(registrationId, data ?? null),
      invalidate: () => invalidateAppServices(),
    },
    {
      ...rest,
      onError: (...args) => {
        void invalidateAppServices();
        onError?.(...args);
      },
    }
  );
};
