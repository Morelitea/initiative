import { Link } from "react-router-dom";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import type { Project } from "@/types/api";
import { Button } from "@/components/ui/button";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";

interface ProjectTabsBarProps {
  projects?: Project[];
  activeProjectId?: number | null;
  loading?: boolean;
  onClose: (projectId: number) => void;
}

export const ProjectTabsBar = ({
  projects,
  activeProjectId,
  loading,
  onClose,
}: ProjectTabsBarProps) => {
  if (!loading && (!projects || projects.length === 0)) {
    return null;
  }

  return (
    <ScrollArea className="h-12 pt-2.5">
      <div className="flex h-full items-end gap-2 px-4">
        {loading ? (
          <p className="text-muted-foreground py-3 text-xs">Loading recent projects…</p>
        ) : (
          projects?.map((project) => {
            const isActive = project.id === activeProjectId;
            return (
              <div key={project.id} className="flex items-center">
                <Link
                  to={`/projects/${project.id}`}
                  className={cn(
                    "group inline-flex items-center gap-2 rounded-t-md border border-transparent px-3 py-2 text-sm transition",
                    isActive
                      ? "border-border bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {project.initiative ? (
                    <InitiativeColorDot color={project.initiative.color} className="h-2 w-2" />
                  ) : null}
                  {project.icon ? (
                    <span className="text-base leading-none">{project.icon}</span>
                  ) : null}
                  <span className="max-w-40 truncate">{project.name}</span>
                </Link>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="text-muted-foreground hover:text-foreground ml-1 h-7 w-7"
                  onClick={(event) => {
                    event.preventDefault();
                    onClose(project.id);
                  }}
                  aria-label={`Close ${project.name}`}
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </div>
            );
          })
        )}
      </div>
      <ScrollBar orientation="horizontal" />
    </ScrollArea>
  );
};
