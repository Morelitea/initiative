import { useGuilds } from "@/hooks/useGuilds";

/**
 * The active guild id for guild-scoped API calls.
 *
 * Sourced from the guild context, which mirrors the `/g/$guildId` route
 * segment. Guild-scoped hooks pass this to the path-based
 * (`/api/v1/g/{guild_id}/...`) generated client. Only meaningful inside the
 * guild route tree; personal/cross-guild pages (`/me/*`) call the dedicated
 * cross-guild endpoints and do not use guild-scoped hooks.
 *
 * Returns 0 when there is no active guild (personal mode) — guild-scoped hooks
 * are not used there, so the value is never sent.
 */
export function useActiveGuildId(): number {
  const { activeGuildId } = useGuilds();
  return activeGuildId ?? 0;
}
