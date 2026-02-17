import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { FolderKanban } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useGuildPath } from "@/lib/guildUrl";
import type { Project } from "@/types/api";

interface ProjectHealthListProps {
  projects: Project[];
  isLoading?: boolean;
}

function getHealthPercent(project: Project): number {
  const summary = project.task_summary;
  if (!summary || summary.total === 0) return 0;
  return Math.round((summary.completed / summary.total) * 100);
}

export function ProjectHealthList({ projects, isLoading }: ProjectHealthListProps) {
  const { t } = useTranslation("dashboard");
  const gp = useGuildPath();

  const sorted = [...projects]
    .filter((p) => !p.is_archived && p.task_summary && p.task_summary.total > 0)
    .sort((a, b) => getHealthPercent(a) - getHealthPercent(b))
    .slice(0, 6);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>{t("projectHealth.title")}</CardTitle>
          <CardDescription>{t("projectHealth.description")}</CardDescription>
        </div>
        <Button variant="ghost" size="sm" asChild>
          <Link to={gp("/projects")}>{t("projectHealth.viewAll")}</Link>
        </Button>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="space-y-2">
                <Skeleton className="h-4 w-1/3" />
                <Skeleton className="h-2 w-full" />
              </div>
            ))}
          </div>
        ) : sorted.length === 0 ? (
          <div className="text-muted-foreground flex h-[200px] items-center justify-center text-sm">
            <div className="flex flex-col items-center gap-2">
              <FolderKanban className="h-8 w-8 opacity-50" />
              <span>{t("projectHealth.noProjects")}</span>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {sorted.map((project) => {
              const percent = getHealthPercent(project);
              const total = project.task_summary?.total ?? 0;
              return (
                <Link
                  key={project.id}
                  to={gp(`/projects/${project.id}`)}
                  className="hover:bg-accent block space-y-1.5 rounded-md p-2 transition-colors"
                >
                  <div className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-2 font-medium">
                      {project.icon && <span>{project.icon}</span>}
                      {project.name}
                    </span>
                    <span className="text-muted-foreground text-xs">
                      {t("projectHealth.tasks", { count: total })}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Progress value={percent} className="h-2 flex-1" />
                    <span className="text-muted-foreground w-10 text-right text-xs">
                      {percent}%
                    </span>
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
