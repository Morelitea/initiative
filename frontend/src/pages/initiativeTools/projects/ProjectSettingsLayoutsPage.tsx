/**
 * `/settings/layouts` — how this project draws its tasks: each of its layouts,
 * when it was last changed, and which list it opens on, with the way into the
 * layout editor.
 *
 * Changing them is a step above write access (the project's owner, the
 * initiative's managers, or a community admin). The server decides, and says
 * so on the set. The tab bar offers this section only then, and the section
 * refuses anyone else on its own too, since the address is typeable.
 */

import { Link, useParams } from "@tanstack/react-router";
import { Pencil } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { LayoutList } from "@/components/layouts/LayoutList";
import { ToolSettingsPermissionRequired } from "@/components/tools/settings/ToolSettingsGuard";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useProjectLayouts } from "@/hooks/useToolLayouts";
import { atLeast, useWidthClass } from "@/hooks/useWidthClass";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolDetailRoute } from "@/lib/tools";

export const ProjectSettingsLayoutsPage = () => {
  const { projectId, initiativeId } = useParams({ strict: false }) as {
    projectId?: string;
    initiativeId?: string;
  };
  const { t } = useTranslation("projects");
  const gp = useCommunityPath();
  const wide = atLeast(useWidthClass(), "md");
  const parsedId = projectId ? Number(projectId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);

  const set = useProjectLayouts(isValidId ? parsedId : null).data;

  if (!set) return null;
  if (!set.can_configure) return <ToolSettingsPermissionRequired />;

  const editor = gp(`${toolDetailRoute(Tool.project, Number(initiativeId), parsedId)}/layouts`);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("layouts.heading")}</CardTitle>
        <CardDescription>{t("layouts.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <LayoutList layouts={set.layouts} />
        {/* The editor needs a tablet-sized screen; it says so itself too. */}
        {wide ? (
          <Button asChild variant="outline" size="sm">
            <Link to={editor}>
              <Pencil className="h-4 w-4" />
              {t("layoutEditor.open")}
            </Link>
          </Button>
        ) : (
          <p className="text-muted-foreground text-sm">{t("layoutEditor.compact")}</p>
        )}
      </CardContent>
    </Card>
  );
};
