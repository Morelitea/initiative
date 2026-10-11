/**
 * `/settings/layouts` — how each tool in this initiative draws what it holds,
 * in the sidebar's order: the calendar's event detail, then each project's
 * layouts. Each layout says when it was last changed, and a project which list
 * it opens on; each has a way into its layout editor.
 */

import { Link } from "@tanstack/react-router";
import { Pencil } from "lucide-react";
import { useTranslation } from "react-i18next";

import { type InitiativeToolLayoutsRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { InitiativeSettingsPermissionRequired } from "@/components/initiatives/settings/InitiativeSettingsGuard";
import { LayoutList } from "@/components/layouts/LayoutList";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useInitiativeSettings } from "@/hooks/useInitiativeSettings";
import { calendarTarget, useInitiativeLayouts, useToolLayouts } from "@/hooks/useToolLayouts";
import { atLeast, useWidthClass } from "@/hooks/useWidthClass";
import { useCommunityPath } from "@/lib/communityUrl";
import { isToolEnabled, SIDEBAR_TOOLS, toolDetailRoute, toolListRoute } from "@/lib/tools";

export const InitiativeSettingsLayoutsPage = () => {
  const { initiativeId, initiative, canManageMembers } = useInitiativeSettings();
  if (!canManageMembers) return <InitiativeSettingsPermissionRequired />;
  return (
    <InitiativeLayouts
      initiativeId={initiativeId}
      calendar={initiative !== null && isToolEnabled(Tool.calendar, initiative)}
    />
  );
};

/** The tools with layouts, in the order the sidebar lists them. */
const TOOLS_WITH_LAYOUTS = SIDEBAR_TOOLS.filter(
  (tool) => tool === Tool.calendar || tool === Tool.project
);

const InitiativeLayouts = ({
  initiativeId,
  calendar,
}: {
  initiativeId: number;
  /** Whether the initiative has its calendar on. */
  calendar: boolean;
}) => {
  const { t } = useTranslation("initiatives");
  const { data, isError } = useInitiativeLayouts(initiativeId);
  const projects = isError ? (
    <p className="text-destructive text-sm">{t("settings.layouts.loadError")}</p>
  ) : data?.length === 0 ? (
    <p className="text-muted-foreground text-sm">{t("settings.layouts.noProjects")}</p>
  ) : (
    data?.map((entry) => (
      <ProjectLayouts key={entry.tool_id} initiativeId={initiativeId} entry={entry} />
    ))
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.layouts.heading")}</CardTitle>
        <CardDescription>{t("settings.layouts.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {TOOLS_WITH_LAYOUTS.map((tool) =>
          tool === Tool.project ? (
            <div key={tool} className="space-y-3">
              {projects}
            </div>
          ) : calendar ? (
            <CalendarLayouts key={tool} initiativeId={initiativeId} />
          ) : null
        )}
      </CardContent>
    </Card>
  );
};

/** One project's layouts, opening its editor where the reader may change them
 *  and has the room the editor needs. */
const ProjectLayouts = ({
  initiativeId,
  entry,
}: {
  initiativeId: number;
  entry: InitiativeToolLayoutsRead;
}) => {
  const { t } = useTranslation("projects");
  const gp = useCommunityPath();
  const wide = atLeast(useWidthClass(), "md");
  const project = gp(toolDetailRoute(Tool.project, initiativeId, entry.tool_id));
  const editor = `${project}/layouts`;
  return (
    <section aria-label={entry.name} className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link to={project} className="font-medium hover:underline">
          {entry.name}
        </Link>
        {entry.can_configure && wide ? (
          <Button asChild variant="outline" size="sm">
            <Link to={editor}>
              <Pencil className="h-4 w-4" />
              {t("layoutEditor.open")}
            </Link>
          </Button>
        ) : null}
      </div>
      <LayoutList layouts={entry.layouts} />
    </section>
  );
};

/** The calendar's event detail, which every calendar in the initiative shares,
 *  opening its editor where the reader may change it and has the room. */
const CalendarLayouts = ({ initiativeId }: { initiativeId: number }) => {
  const { t } = useTranslation(["initiatives", "projects"]);
  const gp = useCommunityPath();
  const wide = atLeast(useWidthClass(), "md");
  const set = useToolLayouts(calendarTarget(initiativeId)).data;
  if (!set) return null;
  const calendars = gp(toolListRoute(Tool.calendar, initiativeId));
  const editor = `${calendars}/layouts`;
  // The calendar's own list draws nothing a layout can change yet.
  const details = set.layouts.filter((layout) => !("is_default" in layout));
  return (
    <section aria-label={t("settings.layouts.calendar")} className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link to={calendars} className="font-medium hover:underline">
          {t("settings.layouts.calendar")}
        </Link>
        {set.can_configure && wide ? (
          <Button asChild variant="outline" size="sm">
            <Link to={editor}>
              <Pencil className="h-4 w-4" />
              {t("projects:layoutEditor.open")}
            </Link>
          </Button>
        ) : null}
      </div>
      <LayoutList layouts={details} />
    </section>
  );
};
