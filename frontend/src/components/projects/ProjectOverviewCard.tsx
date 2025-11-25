import type { CSSProperties } from "react";
import { useMemo } from "react";

import { Badge } from "@/components/ui/badge";
import { Markdown } from "@/components/Markdown";
import { FavoriteProjectButton } from "./FavoriteProjectButton";
import {
  InitiativeColorDot,
  INITIATIVE_COLOR_FALLBACK,
  resolveInitiativeColor,
} from "@/lib/initiativeColors";
import type { Project } from "@/types/api";

type ProjectOverviewCardProps = {
  project: Project;
  projectIsArchived: boolean;
};

export const ProjectOverviewCard = ({ project, projectIsArchived }: ProjectOverviewCardProps) => {
  const detailCardStyle = useMemo(() => {
    const initiativeColor = resolveInitiativeColor(project.initiative?.color);
    return buildProjectDetailBackground(initiativeColor);
  }, [project.initiative?.color]);

  return (
    <div className="space-y-4 rounded-2xl border bg-card/90 p-6 shadow-sm" style={detailCardStyle}>
      <div className="flex flex-wrap items-center gap-2 sm:gap-3">
        <div className="flex flex-1 items-center gap-2 sm:gap-3">
          {project.icon ? (
            <span className="text-xl leading-none sm:text-4xl">{project.icon}</span>
          ) : null}
          <h1 className="text-xl font-semibold tracking-tight sm:text-3xl">{project.name}</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <FavoriteProjectButton
            projectId={project.id}
            isFavorited={project.is_favorited ?? false}
          />
          <Badge variant={projectIsArchived ? "destructive" : "secondary"}>
            {projectIsArchived ? "Archived" : "Active"}
          </Badge>
          {project.is_template ? <Badge variant="outline">Template</Badge> : null}
        </div>
      </div>
      {project.initiative ? (
        <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
          <InitiativeColorDot color={project.initiative.color} />
          <span>{project.initiative.name}</span>
        </div>
      ) : null}
      {project.is_template ? (
        <p className="rounded-md border border-muted/70 bg-muted/30 px-4 py-2 text-sm text-muted-foreground">
          This project is a template. Use it to create new projects from the Templates tab.
        </p>
      ) : null}
      {project.description ? <Markdown content={project.description} /> : null}
      {projectIsArchived ? (
        <p className="rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          This project is archived. Unarchive it from settings to add or update tasks.
        </p>
      ) : null}
    </div>
  );
};

const hexToRgba = (hex: string, alpha: number): string => {
  const sanitized = hex.replace("#", "");
  const expanded =
    sanitized.length === 3
      ? sanitized
          .split("")
          .map((char) => char + char)
          .join("")
      : sanitized.padEnd(6, "0");
  const r = parseInt(expanded.slice(0, 2), 16);
  const g = parseInt(expanded.slice(2, 4), 16);
  const b = parseInt(expanded.slice(4, 6), 16);

  if ([r, g, b].some((value) => Number.isNaN(value))) {
    return hexToRgba(INITIATIVE_COLOR_FALLBACK, alpha);
  }

  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

const buildProjectDetailBackground = (hexColor: string): CSSProperties => {
  return {
    borderColor: hexToRgba(hexColor, 0.35),
    backgroundImage: `linear-gradient(135deg, ${hexToRgba(hexColor, 0.18)} 0%, ${hexToRgba(
      hexColor,
      0.06
    )} 45%, transparent 100%)`,
  };
};
