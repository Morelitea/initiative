import { HTMLAttributes } from "react";
import { Link } from "react-router-dom";
import { GripVertical } from "lucide-react";

import { Card, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { FavoriteProjectButton } from "@/components/projects/FavoriteProjectButton";
import { PinProjectButton } from "@/components/projects/PinProjectButton";
import { InitiativeColorDot, resolveInitiativeColor } from "@/lib/initiativeColors";
import type { Initiative, Project } from "@/types/api";

interface ProjectLinkProps {
  project: Project;
  dragHandleProps?: HTMLAttributes<HTMLButtonElement>;
  canPinProjects: boolean;
}

export const ProjectCardLink = ({ project, dragHandleProps, canPinProjects }: ProjectLinkProps) => {
  const initiative = project.initiative;
  const initiativeColor = initiative ? resolveInitiativeColor(initiative.color) : null;
  const isPinned = Boolean(project.pinned_at);

  return (
    <div className="relative">
      <div className="absolute top-4 right-4 z-10 flex items-center gap-2">
        <PinProjectButton
          projectId={project.id}
          isPinned={isPinned}
          canPin={canPinProjects}
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
      <Link to={`/projects/${project.id}`} className="block">
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
          <CardFooter className="text-muted-foreground flex justify-between gap-6 space-y-2 text-sm">
            <div>
              <InitiativeLabel initiative={initiative} />
              <p>Updated {new Date(project.updated_at).toLocaleDateString(undefined)}</p>
            </div>

            <div className="flex-1">
              <ProjectProgress summary={project.task_summary} />
            </div>
          </CardFooter>
        </Card>
      </Link>
    </div>
  );
};

export const ProjectRowLink = ({ project, dragHandleProps, canPinProjects }: ProjectLinkProps) => {
  const initiativeColor = project.initiative
    ? resolveInitiativeColor(project.initiative.color)
    : null;
  const isPinned = Boolean(project.pinned_at);
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
            canPin={canPinProjects}
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
      <Link to={`/projects/${project.id}`} className="block">
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
                    <p>Updated {new Date(project.updated_at).toLocaleDateString(undefined)}</p>
                    <InitiativeLabel initiative={project.initiative} />
                  </div>
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
  if (!initiative) {
    return null;
  }
  return (
    <Link
      to={`/initiatives/${initiative.id}`}
      className="text-muted-foreground flex items-center gap-2 text-xs font-medium"
    >
      <InitiativeColorDot color={initiative.color} />
      {initiative.name}
    </Link>
  );
};

export const ProjectProgress = ({ summary }: { summary?: Project["task_summary"] }) => {
  const total = summary?.total ?? 0;
  const completed = summary?.completed ?? 0;
  if (total === 0) {
    return <p className="text-muted-foreground text-xs">No tasks yet</p>;
  }
  const percentage = Math.min(100, Math.round((completed / total) * 100));
  return (
    <div>
      <div className="flex items-center justify-between text-xs">
        <span>{completed} done</span>
        <span>{percentage}%</span>
      </div>
      <div className="bg-muted mt-1 h-1.5 rounded-full">
        <div
          className="bg-primary h-1.5 rounded-full transition-all"
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
};
