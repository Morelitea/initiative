import { useQuery } from "@tanstack/react-query";

import {
  getAppConfigApiV1ConfigGet,
  getGetAppConfigApiV1ConfigGetQueryKey,
} from "@/api/generated/config/config";
import type { AppConfig } from "@/api/generated/initiativeAPI.schemas";

/**
 * Runtime config fetched once at boot.
 *
 * The backend serves deployment-specific values (like the optional
 * advanced-tool URL) here because Vite vars are baked into the static
 * bundle at build time and can't change between deployments. One image,
 * many envs.
 *
 * Stays cached effectively forever within a session — the values only
 * change when the operator restarts the backend with new env vars, at
 * which point a page reload will re-fetch.
 */
export const useAppConfig = () => {
  const query = useQuery<AppConfig>({
    queryKey: getGetAppConfigApiV1ConfigGetQueryKey(),
    queryFn: () => getAppConfigApiV1ConfigGet() as unknown as Promise<AppConfig>,
    staleTime: Infinity,
    gcTime: Infinity,
    retry: 1,
  });

  return {
    config: query.data,
    isLoading: query.isLoading,
    /** Convenience: when this is null, the toggle and panel must be fully hidden. */
    advancedTool: query.data?.advanced_tool ?? null,
  };
};
