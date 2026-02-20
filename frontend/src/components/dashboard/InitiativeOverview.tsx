import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Layers } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useGuildPath } from "@/lib/guildUrl";
import type { InitiativeRead, ProjectRead } from "@/api/generated/initiativeAPI.schemas";

interface InitiativeOverviewProps {
  initiatives: InitiativeRead[];
  projects: ProjectRead[];
  isLoading?: boolean;
}

export function InitiativeOverview({ initiatives, projects, isLoading }: InitiativeOverviewProps) {
  const { t } = useTranslation("dashboard");
  const gp = useGuildPath();

  const items = initiatives.map((initiative) => ({
    ...initiative,
    projectCount: projects.filter((p) => p.initiative_id === initiative.id && !p.is_archived)
      .length,
  }));

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>{t("initiatives.title")}</CardTitle>
          <CardDescription>{t("initiatives.description")}</CardDescription>
        </div>
        <Button variant="ghost" size="sm" asChild>
          <Link to={gp("/initiatives")}>{t("initiatives.viewAll")}</Link>
        </Button>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="text-muted-foreground flex h-[120px] items-center justify-center text-sm">
            <div className="flex flex-col items-center gap-2">
              <Layers className="h-8 w-8 opacity-50" />
              <span>{t("initiatives.noInitiatives")}</span>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {items.map((initiative) => (
              <Link
                key={initiative.id}
                to={gp(`/initiatives/${initiative.id}`)}
                className="hover:bg-accent flex items-start gap-3 rounded-lg border p-3 transition-colors"
              >
                <div
                  className="mt-0.5 h-3 w-3 shrink-0 rounded-full"
                  style={{ backgroundColor: initiative.color || "var(--muted)" }}
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{initiative.name}</p>
                  <div className="text-muted-foreground mt-1 flex items-center gap-2 text-xs">
                    <span>{t("initiatives.member", { count: initiative.members.length })}</span>
                    <span aria-hidden="true">&middot;</span>
                    <span>{t("initiatives.project", { count: initiative.projectCount })}</span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
