import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/calendars/$calendarId/settings/advanced"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/toolSettings/ToolSettingsAdvancedPage").then((m) => ({
      default: m.ToolSettingsAdvancedPage,
    }))
  ),
});
