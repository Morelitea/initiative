import { ReactNode, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ChevronRight, Clock3, Star, X } from "lucide-react";

import { cn } from "../../lib/utils";
import { InitiativeColorDot } from "../../lib/initiativeColors";
import type { Project } from "../../types/api";
import { Button } from "../ui/button";

interface ProjectShortcutsSidebarProps {
  favorites?: Project[];
  recent?: Project[];
  loading?: boolean;
  onClearRecent: (projectId: number) => void;
  className?: string;
}

const Section = ({
  title,
  icon,
  items,
  collapsed,
  onToggle,
  emptyMessage,
  onClearRecent,
}: {
  title: string;
  icon: ReactNode;
  items: Project[] | undefined;
  collapsed: boolean;
  onToggle: () => void;
  emptyMessage: string;
  onClearRecent?: (projectId: number) => void;
}) => (
  <div>
    <button
      type="button"
      className="flex w-full items-center justify-between rounded-md px-2 py-1 text-sm font-semibold text-muted-foreground transition hover:text-foreground"
      onClick={onToggle}
    >
      <span className="inline-flex items-center gap-2">
        {icon}
        {title}
      </span>
      {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
    </button>
    {!collapsed ? (
      <div className="mt-2 space-y-1">
        {items && items.length > 0 ? (
          items.map((project) => (
            <div
              key={project.id}
              className="group flex items-center justify-between rounded-md px-2 py-1 text-sm"
            >
              <Link
                to={`/projects/${project.id}`}
                className="flex flex-1 items-center gap-2 truncate text-muted-foreground transition group-hover:text-foreground"
              >
                {project.initiative ? (
                  <InitiativeColorDot color={project.initiative.color} className="h-2 w-2" />
                ) : null}
                {project.icon ? (
                  <span className="text-base leading-none">{project.icon}</span>
                ) : null}
                <span className="truncate">{project.name}</span>
              </Link>
              {onClearRecent ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 text-muted-foreground opacity-0 transition group-hover:opacity-100"
                  onClick={(event) => {
                    event.preventDefault();
                    onClearRecent(project.id);
                  }}
                >
                  <X className="h-3 w-3" />
                </Button>
              ) : null}
            </div>
          ))
        ) : (
          <p className="px-2 text-xs text-muted-foreground">{emptyMessage}</p>
        )}
      </div>
    ) : null}
  </div>
);

export const ProjectShortcutsSidebar = ({
  favorites,
  recent,
  loading,
  onClearRecent,
  className,
}: ProjectShortcutsSidebarProps) => {
  const [favoritesCollapsed, setFavoritesCollapsed] = useState(false);
  const [recentCollapsed, setRecentCollapsed] = useState(false);

  return (
    <aside
      className={cn(
        "hidden w-72 flex-shrink-0 flex-col border-r bg-card/40 p-4 text-sm lg:flex",
        className
      )}
    >
      <h2 className="mb-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Projects
      </h2>
      {loading ? (
        <p className="text-xs text-muted-foreground">Loading shortcuts…</p>
      ) : (
        <div className="space-y-4">
          <Section
            title="Favorites"
            icon={<Star className="h-4 w-4 text-amber-500" />}
            items={favorites}
            collapsed={favoritesCollapsed}
            onToggle={() => setFavoritesCollapsed((prev) => !prev)}
            emptyMessage="No favorites yet."
          />
          <Section
            title="Recently opened"
            icon={<Clock3 className="h-4 w-4" />}
            items={recent}
            collapsed={recentCollapsed}
            onToggle={() => setRecentCollapsed((prev) => !prev)}
            emptyMessage="Open a project to see it here."
            onClearRecent={onClearRecent}
          />
        </div>
      )}
    </aside>
  );
};
