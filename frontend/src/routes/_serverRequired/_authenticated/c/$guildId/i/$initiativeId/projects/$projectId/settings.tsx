import { createFileRoute, lazyRouteComponent, redirect } from "@tanstack/react-router";

const SETTINGS = "/c/$guildId/i/$initiativeId/projects/$projectId/settings" as const;

/** The sections used to be a `?tab=` selector on this one page; each is now a
 *  route. Keeps old bookmarks and links pointing at the right one. */
const SECTION_FOR_TAB = {
  access: `${SETTINGS}/access`,
  advanced: `${SETTINGS}/advanced`,
  "filter-presets": `${SETTINGS}/filter-presets`,
  "task-statuses": `${SETTINGS}/task-statuses`,
} as const;

/**
 * Layout for one project's settings: the header, the tab bar, and whichever
 * section the address names. Each section is a route of its own beneath this
 * one, so `/settings/task-statuses` can be linked to and bookmarked.
 */
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/projects/$projectId/settings"
)({
  validateSearch: (search: Record<string, unknown>) => ({
    tab: typeof search.tab === "string" ? search.tab : undefined,
  }),
  beforeLoad: ({ params, search }) => {
    if (!search.tab) return;
    throw redirect({
      // A tab this project never had lands on Details, the same fallback the
      // old page used.
      to: SECTION_FOR_TAB[search.tab as keyof typeof SECTION_FOR_TAB] ?? SETTINGS,
      params,
      search: { tab: undefined },
    });
  },
  component: lazyRouteComponent(() =>
    import("@/pages/ProjectSettingsPage").then((m) => ({ default: m.ProjectSettingsPage }))
  ),
});
