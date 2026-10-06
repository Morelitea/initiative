import { Link } from "@tanstack/react-router";
import { GripVertical } from "lucide-react";
import type { HTMLAttributes, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { type ProjectRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { UnreadDot } from "@/components/notifications/UnreadDot";
import { FavoriteProjectButton } from "@/components/projects/FavoriteProjectButton";
import { PinProjectButton } from "@/components/projects/PinProjectButton";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { Badge } from "@/components/ui/badge";
import { Card, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { ProgressCircle } from "@/components/ui/progress-circle";
import { useUnreadTree } from "@/hooks/useUnreadTree";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolDetailRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

interface ProjectLinkProps {
  project: ProjectRead;
  dragHandleProps?: HTMLAttributes<HTMLButtonElement>;
  /** Extra controls for the card's top-right cluster — rendered outside the
   *  wrapping link so they stay valid (and clickable) inside a card-as-anchor.
   *  Used by the Templates and Archive lists for their per-project action. */
  actions?: ReactNode;
}

export const ProjectCardLink = ({ project, dragHandleProps, actions }: ProjectLinkProps) => {
  const { t } = useTranslation("projects");
  const gp = useCommunityPath();
  const unread = useUnreadTree();
  const isPinned = Boolean(project.pinned_at);
  const canPin = project.can.configure;

  return (
    <div className="relative">
      <div className="absolute top-4 right-4 z-10 flex items-center gap-2">
        {actions}
        <PinProjectButton
          projectId={project.id}
          isPinned={isPinned}
          canPin={canPin}
          suppressNavigation
        />
        <FavoriteProjectButton
          projectId={project.id}
          isFavorited={project.is_favorited ?? false}
          suppressNavigation
        />
        {dragHandleProps ? (
          <button
            type="button"
            className="rounded-md p-1 text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={t("preview.reorder")}
            {...dragHandleProps}
          >
            <GripVertical className="h-4 w-4" />
          </button>
        ) : null}
      </div>
      <Link
        to={gp(toolDetailRoute(Tool.project, project.initiative_id, project.id))}
        className="block"
      >
        <Card className="overflow-hidden">
          <CardHeader className={actions ? "pr-32" : "pr-22"}>
            <CardTitle className="flex flex-wrap items-center gap-2 text-xl">
              {project.icon ? <span className="text-2xl leading-none">{project.icon}</span> : null}
              <span>{project.name}</span>
              {unread.hasResource(project.community_id, Tool.project, project.id) ? (
                <UnreadDot />
              ) : null}
              <ProjectStateBadge project={project} />
            </CardTitle>
          </CardHeader>
          <CardFooter className="flex flex-col gap-3 text-muted-foreground text-sm">
            <div className="flex w-full justify-between gap-6">
              <div>
                <p>
                  {t("preview.updated", {
                    date: new Date(project.updated_at).toLocaleDateString(undefined),
                  })}
                </p>
                {project.archived_at ? (
                  <p>
                    {t("preview.archivedOn", {
                      date: new Date(project.archived_at).toLocaleDateString(undefined),
                    })}
                  </p>
                ) : null}
              </div>
              <div className="flex-1">
                <ProjectProgress summary={project.task_summary} />
              </div>
            </div>
            <TagBadgeList
              tags={project.tags}
              limit={4}
              tagHref={(tag) => gp(`/tags/${tag.id}`)}
              nested
              className="w-full"
            />
          </CardFooter>
        </Card>
      </Link>
    </div>
  );
};

export const ProjectRowLink = ({ project, dragHandleProps, actions }: ProjectLinkProps) => {
  const { t } = useTranslation("projects");
  const gp = useCommunityPath();
  const unread = useUnreadTree();
  const isPinned = Boolean(project.pinned_at);
  const canPin = project.can.configure;
  return (
    <div className="relative">
      {dragHandleProps ? (
        <button
          type="button"
          className="absolute top-1/2 left-4 z-10 -translate-y-1/2 rounded-md p-1 text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={t("preview.reorder")}
          {...dragHandleProps}
        >
          <GripVertical className="h-4 w-4" />
        </button>
      ) : null}
      <div className="absolute top-4 right-4 z-10">
        <div className="flex items-center gap-2">
          {actions}
          <PinProjectButton
            projectId={project.id}
            isPinned={isPinned}
            canPin={canPin}
            suppressNavigation
            iconSize="sm"
          />
          <FavoriteProjectButton
            projectId={project.id}
            isFavorited={project.is_favorited ?? false}
            suppressNavigation
            iconSize="sm"
          />
        </div>
      </div>
      <Link
        to={gp(toolDetailRoute(Tool.project, project.initiative_id, project.id))}
        className="block"
      >
        <Card className={cn("p-4 pr-16", actions && "pr-24")}>
          <div className={`flex flex-wrap items-center gap-4 ${dragHandleProps ? "pl-10" : ""}`}>
            {project.icon ? <span className="text-2xl leading-none">{project.icon}</span> : null}
            <div className="min-w-[200px] flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-semibold">{project.name}</p>
                {unread.hasResource(project.community_id, Tool.project, project.id) ? (
                  <UnreadDot />
                ) : null}
                <ProjectStateBadge project={project} />
              </div>
              <div className="flex flex-wrap gap-6">
                <div className="min-w-30 flex-1">
                  <div className="mt-1 flex flex-wrap items-center gap-3 text-muted-foreground text-xs">
                    <p>
                      {t("preview.updated", {
                        date: new Date(project.updated_at).toLocaleDateString(undefined),
                      })}
                    </p>
                    {project.archived_at ? (
                      <p>
                        {t("preview.archivedOn", {
                          date: new Date(project.archived_at).toLocaleDateString(undefined),
                        })}
                      </p>
                    ) : null}
                  </div>
                  <TagBadgeList
                    tags={project.tags}
                    limit={4}
                    tagHref={(tag) => gp(`/tags/${tag.id}`)}
                    nested
                    className="mt-2"
                  />
                </div>
                <div className="flex-1">
                  <ProjectProgress summary={project.task_summary} />
                </div>
              </div>
            </div>
          </div>
        </Card>
      </Link>
    </div>
  );
};

/** Marks a card that is not an ordinary active project, so template and
 *  archived projects stay recognizable wherever they are listed. */
const ProjectStateBadge = ({ project }: { project: ProjectRead }) => {
  const { t } = useTranslation(["projects", "common"]);
  if (project.is_template) {
    return <Badge variant="outline">{t("common:toolChest.template")}</Badge>;
  }
  if (project.archived_at !== null) {
    return <Badge variant="outline">{t("common:toolChest.archived")}</Badge>;
  }
  return null;
};

const ProjectProgress = ({ summary }: { summary?: ProjectRead["task_summary"] }) => {
  const { t } = useTranslation("projects");
  const total = summary?.total ?? 0;
  const completed = summary?.completed ?? 0;
  const percent = total > 0 ? Math.round((completed / total) * 100) : 0;

  return (
    <div className="@container flex w-full items-center justify-between gap-4">
      <div className="@xs:flex hidden w-full flex-col gap-2">
        <span className="flex justify-end text-muted-foreground text-xs">
          {t("preview.tasksDone", { completed, total })}
        </span>
        <Progress value={percent} className="h-2" aria-label={t("progressLabel")} />
      </div>
      <div className="flex @xs:hidden w-full items-center justify-end gap-3">
        <ProgressCircle value={percent} />
      </div>
    </div>
  );
};
