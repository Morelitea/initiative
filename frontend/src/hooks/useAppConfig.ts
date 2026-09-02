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
 * Cached hard, but not forever. Most of these only change when the operator
 * restarts the backend with new env vars, at which point a page reload
 * re-fetches. The community directory is the exception: it is a database
 * setting an owner can change while people are using the app, and everyone
 * else's client has to arrive at the same answer.
 *
 * So the owner's own write invalidates this query (immediate for them), and
 * every other client re-checks when it next comes back to the tab or mounts a
 * consumer — at most once per CONFIG_STALE_MS. That is one small request on
 * returning to a tab, against a config that would otherwise stay wrong until
 * the page was reloaded.
 */
/** How long a client may go on believing what it was told. Long enough that
 *  this is not a poll, short enough that the community directory being
 *  switched on or off reaches an open tab on its own. */
const CONFIG_STALE_MS = 5 * 60 * 1000;

export const useAppConfig = () => {
  const query = useQuery<AppConfig>({
    queryKey: getGetAppConfigApiV1ConfigGetQueryKey(),
    queryFn: () => getAppConfigApiV1ConfigGet(),
    staleTime: CONFIG_STALE_MS,
    gcTime: Infinity,
    // Opted in against the client-wide default: this is the query whose answer
    // can change without the viewer doing anything, and coming back to the tab
    // is the moment to find that out.
    refetchOnWindowFocus: true,
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
    /** Whether this deployment asks an account to confirm it is 13 or older
     *  before it belongs to a listed guild. True until the config loads, and
     *  true is also the default — the question is the safe thing to ask when
     *  we do not yet know, and the server refuses the join either way. */
    communityAgeGateEnabled: query.data?.community_age_gate_enabled ?? true,
  };
};
