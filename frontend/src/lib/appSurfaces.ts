/**
 * What an installed app offers a member, read off its pinned definition.
 *
 * Three shapes, and the sidebar treats each differently:
 *
 * - **A surface** — one or more embedded pages. Opens a page of its own.
 * - **Something to connect** — no page, but a credential the member or an
 *   admin supplies. Opens a dialog where they do that.
 * - **Neither** — it contributes widgets or data to somewhere else. There is
 *   nothing to open, so it does not take a row of its own.
 */

import type { LocalizedText } from "@/api/appConnections";

export interface AppEmbed {
  id: string;
  path: string;
  visibility?: string;
  name?: LocalizedText;
}

/** Loose shape so this reads both the list and detail payloads. */
export interface AppSurfaceSource {
  tool?: string | null;
  artifacts?: { type: string; id: number }[];
  definition?: Record<string, unknown> | null;
}

/** The embedded surfaces an app declared, if any. */
export const appEmbeds = (definition?: Record<string, unknown> | null): AppEmbed[] => {
  const embeds = definition?.embeds;
  if (!Array.isArray(embeds)) return [];
  return embeds.filter(
    (embed): embed is AppEmbed =>
      typeof embed === "object" &&
      embed !== null &&
      typeof (embed as AppEmbed).id === "string" &&
      typeof (embed as AppEmbed).path === "string"
  );
};

/** Whether the app declares any credential to fill in or connect. */
export const appHasConnections = (definition?: Record<string, unknown> | null): boolean =>
  Array.isArray(definition?.connections) && definition.connections.length > 0;

/**
 * Where an app's entry leads.
 *
 * A tool-instance app mounts an existing tool, so it links at the tool's own
 * route — the calendar an app created is just a calendar. A service app with
 * embedded surfaces gets a page. Anything else has no route, and the caller
 * decides what to do with the row.
 */
export const guildAppPath = (app: AppSurfaceSource & { id: number }): string | null => {
  if (app.tool === "calendar") {
    const calendar = (app.artifacts ?? []).find((artifact) => artifact.type === "calendar");
    return calendar ? `/calendars/${calendar.id}` : null;
  }
  return appEmbeds(app.definition).length ? `/apps/${app.id}` : null;
};
