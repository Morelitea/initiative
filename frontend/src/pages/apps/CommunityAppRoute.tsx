import { useParams } from "@tanstack/react-router";

import { CommunityAppPage } from "@/pages/apps/CommunityAppPage";

/** Reads the install id off the route so the page itself takes a plain prop. */
export function CommunityAppRoute() {
  const { appId } = useParams({ strict: false }) as { appId?: string };
  const parsed = Number(appId);
  if (!Number.isFinite(parsed)) return null;
  return <CommunityAppPage appId={parsed} />;
}

/**
 * The same install, read inside one initiative.
 *
 * Both ids come off the route. Which surfaces are on offer is the server's
 * answer for this reader in this initiative; the mint re-derives it under the
 * caller's own session.
 */
export function InitiativeAppRoute() {
  const { appId, initiativeId } = useParams({ strict: false }) as {
    appId?: string;
    initiativeId?: string;
  };
  const parsedApp = Number(appId);
  const parsedInitiative = Number(initiativeId);
  if (!Number.isFinite(parsedApp) || !Number.isFinite(parsedInitiative)) return null;

  return <CommunityAppPage appId={parsedApp} initiativeId={parsedInitiative} />;
}
