/**
 * `/settings/views` — every project's views in this initiative, and whether
 * each lays out its own task page, with a way into each project's editor.
 */

import { Link } from "@tanstack/react-router";
import { FileText, Pencil, Star } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  type InitiativeToolViewsRead,
  Tool,
  type ToolViewSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { InitiativeSettingsPermissionRequired } from "@/components/initiatives/settings/InitiativeSettingsGuard";
import { viewLayouts, viewName } from "@/components/projects/projectTasksConfig";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useInitiativeSettings } from "@/hooks/useInitiativeSettings";
import { useInitiativeViews } from "@/hooks/useProjectViews";
import { atLeast, useWidthClass } from "@/hooks/useWidthClass";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolDetailRoute } from "@/lib/tools";

export const InitiativeSettingsViewsPage = () => {
  const { initiativeId, canManageMembers } = useInitiativeSettings();
  if (!canManageMembers) return <InitiativeSettingsPermissionRequired />;
  return <InitiativeViews initiativeId={initiativeId} />;
};

const InitiativeViews = ({ initiativeId }: { initiativeId: number }) => {
  const { t } = useTranslation("initiatives");
  const { data, isError } = useInitiativeViews(initiativeId);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.views.heading")}</CardTitle>
        <CardDescription>{t("settings.views.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {isError ? (
          <p className="text-destructive text-sm">{t("settings.views.loadError")}</p>
        ) : data?.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("settings.views.noProjects")}</p>
        ) : (
          data?.map((entry) => (
            <ProjectViews key={entry.tool_id} initiativeId={initiativeId} entry={entry} />
          ))
        )}
      </CardContent>
    </Card>
  );
};

/** One project's views, each opening its editor where the reader may change
 *  them and has the room the editor needs. */
const ProjectViews = ({
  initiativeId,
  entry,
}: {
  initiativeId: number;
  entry: InitiativeToolViewsRead;
}) => {
  const { t } = useTranslation(["initiatives", "projects", "common"]);
  const gp = useCommunityPath();
  const wide = atLeast(useWidthClass(), "md");
  const project = gp(toolDetailRoute(Tool.project, initiativeId, entry.tool_id));
  const editor = `${project}/views`;
  const editable = entry.can_configure && wide;
  return (
    <section aria-label={entry.name} className="space-y-2 rounded-md border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link to={project} className="font-medium hover:underline">
          {entry.name}
        </Link>
        {editable ? (
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline" size="sm">
              <Link to={editor}>
                <Pencil className="h-4 w-4" />
                {t("projects:viewEditor.open")}
              </Link>
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link to={editor} search={{ page: "task" }}>
                <FileText className="h-4 w-4" />
                {t("projects:viewEditor.openTaskPage")}
              </Link>
            </Button>
          </div>
        ) : null}
      </div>
      <ul className="flex flex-wrap gap-2">
        {entry.views.map((view) => (
          <li key={view.slug}>
            {editable ? (
              <Link to={editor} search={{ view: view.slug }}>
                <ViewBadge view={view} />
              </Link>
            ) : (
              <ViewBadge view={view} />
            )}
          </li>
        ))}
      </ul>
      <p className="text-muted-foreground text-xs">
        {[
          entry.stored ? null : t("settings.views.shippedViews"),
          t(
            entry.has_item_layout ? "settings.views.ownTaskPage" : "settings.views.shippedTaskPage"
          ),
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
    </section>
  );
};

const ViewBadge = ({ view }: { view: ToolViewSummary }) => {
  const { t } = useTranslation(["projects", "common", "initiatives"]);
  const Icon = viewLayouts[view.layout].icon;
  return (
    <Badge variant="secondary" className="gap-1">
      <Icon className="h-3 w-3" aria-hidden="true" />
      {viewName(view, t)}
      {view.is_default ? (
        <Star
          className="h-3 w-3 fill-current"
          aria-label={t("initiatives:settings.views.default")}
          role="img"
        />
      ) : null}
    </Badge>
  );
};
