import { useParams } from "@tanstack/react-router";

import { GuildAppPage } from "@/pages/apps/GuildAppPage";

/** Reads the install id off the route so the page itself takes a plain prop. */
export function GuildAppRoute() {
  const { appId } = useParams({ strict: false }) as { appId?: string };
  const parsed = Number(appId);
  if (!Number.isFinite(parsed)) return null;
  return <GuildAppPage appId={parsed} />;
}
