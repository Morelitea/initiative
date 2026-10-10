/**
 * `/settings/layouts` — how each project in this initiative draws its tasks:
 * its layouts, when each was last changed, and which list it opens on, with a
 * way into each project's layout editor.
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
import { useInitiativeLayouts } from "@/hooks/useToolLayouts";
import { atLeast, useWidthClass } from "@/hooks/useWidthClass";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolDetailRoute } from "@/lib/tools";

export const InitiativeSettingsLayoutsPage = () => {
  const { initiativeId, canManageMembers } = useInitiativeSettings();
  if (!canManageMembers) return <InitiativeSettingsPermissionRequired />;
  return <InitiativeLayouts initiativeId={initiativeId} />;
};

const InitiativeLayouts = ({ initiativeId }: { initiativeId: number }) => {
  const { t } = useTranslation("initiatives");
  const { data, isError } = useInitiativeLayouts(initiativeId);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.layouts.heading")}</CardTitle>
        <CardDescription>{t("settings.layouts.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {isError ? (
          <p className="text-destructive text-sm">{t("settings.layouts.loadError")}</p>
        ) : data?.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("settings.layouts.noProjects")}</p>
        ) : (
          data?.map((entry) => (
            <ProjectLayouts key={entry.tool_id} initiativeId={initiativeId} entry={entry} />
          ))
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
