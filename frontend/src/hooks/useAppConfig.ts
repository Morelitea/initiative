import { useQuery } from "@tanstack/react-query";

import {
  getAppConfigApiV1ConfigGet,
  getGetAppConfigApiV1ConfigGetQueryKey,
} from "@/api/generated/config/config";
import type { AppConfig } from "@/api/generated/initiativeAPI.schemas";

/**
 * Runtime config fetched once at boot.
 *
 * The backend serves deployment-specific values (like the optional captcha
 * or billing portal) here because Vite vars are baked into the static
 * bundle at build time and can't change between deployments. One image,
 * many envs.
 *
 * Stays cached effectively forever within a session — most of the values only
 * change when the operator restarts the backend with new env vars, at
 * which point a page reload will re-fetch. The one setting stored in the
 * database rather than the environment (the community directory) invalidates
 * this query when an owner writes it, so their own session updates at once.
 */
export const useAppConfig = () => {
  const query = useQuery<AppConfig>({
    queryKey: getGetAppConfigApiV1ConfigGetQueryKey(),
    queryFn: () => getAppConfigApiV1ConfigGet(),
    staleTime: Infinity,
    gcTime: Infinity,
    retry: 1,
  });

  return {
    config: query.data,
    isLoading: query.isLoading,
    /** When this is null the deployment has no captcha configured —
     *  the SPA must skip the widget on registration. */
    captcha: query.data?.captcha ?? null,
    /** When this is null the deployment has no billing portal configured —
     *  the SPA hides every tier/upgrade/manage surface (the usage panel,
     *  which shows operator-set caps + usage, renders regardless). */
    billing: query.data?.billing ?? null,
    /** Server-enforced upload size cap, for pre-flight checks. Null until the
     *  config loads — skip the client-side check then; the server still
     *  rejects oversized uploads. */
    maxUploadBytes: query.data?.max_upload_bytes ?? null,
    /** Whether this deployment runs a community directory. False until the
     *  config loads, and false is also the default — every way into the
     *  directory stays hidden unless the platform owner turned it on. */
    communityDirectoryEnabled: query.data?.community_directory_enabled ?? false,
  };
};
