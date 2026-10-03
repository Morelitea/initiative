import { useCommunities } from "@/hooks/useCommunities";

/**
 * The active community id for community-scoped API calls.
 *
 * Sourced from the community context, which mirrors the `/c/$communityId` route
 * segment. Community-scoped hooks pass this to the path-based
 * (`/api/v1/c/{community_id}/...`) generated client. Only meaningful inside the
 * community route tree; personal/cross-community pages (`/me/*`) call the dedicated
 * cross-community endpoints and do not use community-scoped hooks.
 *
 * Returns 0 when there is no active community (personal mode) — community-scoped hooks
 * are not used there, so the value is never sent.
 */
export function useActiveCommunityId(): number {
  const { activeCommunityId } = useCommunities();
  return activeCommunityId ?? 0;
}
