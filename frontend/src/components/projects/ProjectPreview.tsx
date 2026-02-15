import { HTMLAttributes } from "react";
import { Link } from "@tanstack/react-router";
import { GripVertical } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Card, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { useGuildPath } from "@/lib/guildUrl";
import { Progress } from "@/components/ui/progress";
import { ProgressCircle } from "@/components/ui/progress-circle";
import { FavoriteProjectButton } from "@/components/projects/FavoriteProjectButton";
import { PinProjectButton } from "@/components/projects/PinProjectButton";
import { TagBadge } from "@/components/tags/TagBadge";
import { useGuilds } from "@/hooks/useGuilds";
import { InitiativeColorDot, resolveInitiativeColor } from "@/lib/initiativeColors";
import type { GuildRole, Initiative, Project } from "@/types/api";

interface ProjectLinkProps {
  project: Project;
  dragHandleProps?: HTMLAttributes<HTMLButtonElement>;
  userId?: number;
}

/**
 * Check if the user can pin/unpin a project.
 * Only guild admins and initiative project managers can pin projects.
 */
const canPinProject = (project: Project, userId?: number, guildRole?: GuildRole): boolean => {
  if (!userId) return false;

  // Guild admins can always pin
  if (guildRole === "admin") return true;

  // Check if user is initiative PM for this project's initiative
  const initiative = project.initiative;
  if (!initiative?.members) return false;

  const membership = initiative.members.find((m) => m.user.id === userId);
  return membership?.role === "project_manager";
};

export const ProjectCardLink = ({ project, dragHandleProps, userId }: ProjectLinkProps) => {
  const { activeGuild } = useGuilds();
  const { t } = useTranslation("projects");
  const gp = useGuildPath();
  const initiative = project.initiative;
  const initiativeColor = initiative ? resolveInitiativeColor(initiative.color) : null;
  const isPinned = Boolean(project.pinned_at);
  const canPin = canPinProject(project, userId, activeGuild?.role);

  return (
    <div className="relative">
      <div className="absolute top-4 right-4 z-10 flex items-center gap-2">
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
            className="bg-background text-muted-foreground hover:text-foreground focus-visible:ring-ring rounded-full border p-1 transition focus-visible:ring-2 focus-visible:outline-none"
            aria-label="Reorder project"
            {...dragHandleProps}
          >
            <GripVertical className="h-4 w-4" />
          </button>
        ) : null}
      </div>
      <Link to={gp(`/projects/${project.id}`)} className="block">
        <Card className="overflow-hidden shadow-sm">
          {initiativeColor ? (
            <div
              className="h-1.5 w-full"
              style={{ backgroundColor: initiativeColor }}
              aria-hidden="true"
            />
          ) : null}
          <CardHeader className="pr-22">
            <CardTitle className="flex items-center gap-2 text-xl">
              {project.icon ? <span className="text-2xl leading-none">{project.icon}</span> : null}
              <span>{project.name}</span>
            </CardTitle>
          </CardHeader>
          <CardFooter className="text-muted-foreground flex flex-col gap-3 text-sm">
            <div className="flex w-full justify-between gap-6">
              <div>
                <InitiativeLabel initiative={initiative} />
                <p>
                  {t("preview.updated", {
                    date: new Date(project.updated_at).toLocaleDateString(undefined),
                  })}
                </p>
              </div>
              <div className="flex-1">
                <ProjectProgress summary={project.task_summary} />
              </div>
            </div>
            {project.tags && project.tags.length > 0 ? (
              <div className="flex w-full flex-wrap gap-1">
                {project.tags.slice(0, 4).map((tag) => (
                  <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} />
                ))}
                {project.tags.length > 4 && (
                  <span className="text-muted-foreground text-xs">+{project.tags.length - 4}</span>
                )}
              </div>
            ) : null}
          </CardFooter>
        </Card>
      </Link>
    </div>
  );
};

export const ProjectRowLink = ({ project, dragHandleProps, userId }: ProjectLinkProps) => {
  const { activeGuild } = useGuilds();
  const { t } = useTranslation("projects");
  const gp = useGuildPath();
  const initiativeColor = project.initiative
    ? resolveInitiativeColor(project.initiative.color)
    : null;
  const isPinned = Boolean(project.pinned_at);
  const canPin = canPinProject(project, userId, activeGuild?.role);
  return (
    <div className="relative">
      {dragHandleProps ? (
        <button
          type="button"
          className="bg-background text-muted-foreground hover:text-foreground focus-visible:ring-ring absolute top-1/2 left-4 z-10 -translate-y-1/2 rounded-full border p-1 transition focus-visible:ring-2 focus-visible:outline-none"
          aria-label="Reorder project"
          {...dragHandleProps}
        >
          <GripVertical className="h-4 w-4" />
        </button>
      ) : null}
      <div className="absolute top-4 right-4 z-10">
        <div className="flex items-center gap-2">
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
      <Link to={gp(`/projects/${project.id}`)} className="block">
        <Card
          className={`p-4 pr-16 shadow-sm ${initiativeColor ? "border-l-4" : ""}`}
          style={initiativeColor ? { borderLeftColor: initiativeColor } : undefined}
        >
          <div className={`flex flex-wrap items-center gap-4 ${dragHandleProps ? "pl-10" : ""}`}>
            {project.icon ? <span className="text-2xl leading-none">{project.icon}</span> : null}
            <div className="min-w-[200px] flex-1">
              <p className="font-semibold">{project.name}</p>
              <div className="flex flex-wrap gap-6">
                <div className="min-w-30 flex-1">
                  <div className="text-muted-foreground mt-1 flex flex-wrap items-center gap-3 text-xs">
                    <p>
                      {t("preview.updated", {
                        date: new Date(project.updated_at).toLocaleDateString(undefined),
                      })}
                    </p>
                    <InitiativeLabel initiative={project.initiative} />
                  </div>
                  {project.tags && project.tags.length > 0 ? (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {project.tags.slice(0, 4).map((tag) => (
                        <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} />
                      ))}
                      {project.tags.length > 4 && (
                        <span className="text-muted-foreground text-xs">
                          +{project.tags.length - 4}
                        </span>
                      )}
                    </div>
                  ) : null}
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

export const InitiativeLabel = ({ initiative }: { initiative?: Initiative | null }) => {
  const gp = useGuildPath();
  if (!initiative) {
    return null;
  }
  return (
    <Link
      to={gp(`/initiatives/${initiative.id}`)}
      className="text-muted-foreground flex items-center gap-2 text-xs font-medium"
    >
      <InitiativeColorDot color={initiative.color} />
      {initiative.name}
    </Link>
  );
};

const ProjectProgress = ({ summary }: { summary?: Project["task_summary"] }) => {
  const { t } = useTranslation("projects");
  const total = summary?.total ?? 0;
  const completed = summary?.completed ?? 0;
  const percent = total > 0 ? Math.round((completed / total) * 100) : 0;

  return (
    <div className="@container flex w-full items-center justify-between gap-4">
      <div className="hidden w-full flex-col gap-2 @xs:flex">
        <span className="text-muted-foreground flex justify-end text-xs">
          {t("preview.tasksDone", { completed, total })}
        </span>
        <Progress value={percent} className="h-2" />
      </div>
      <div className="flex w-full items-center justify-end gap-3 @xs:hidden">
        <ProgressCircle value={percent} />
      </div>
    </div>
  );
};
