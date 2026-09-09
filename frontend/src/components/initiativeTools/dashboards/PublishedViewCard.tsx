/**
 * What this dashboard shows to everybody who can open it.
 *
 * A tile ordinarily answers from whoever is looking at it, which is right
 * almost always and wrong for a figure that has to be common ground. Naming a
 * project here makes every tile read it the same way for every viewer — so
 * this is the author saying "these numbers are mine to share", and it is worth
 * making them say it about each one.
 *
 * Two things the copy has to carry, because they are what makes it safe. It
 * hands on the author's own reach and nothing further, so the list only offers
 * what they can already open. And the owner of what is named keeps it: they
 * see the share on their own project and can take it back whenever they like.
 */

import { Plus, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { DashboardRead, PublishTarget } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useSetPublishedView } from "@/hooks/useDashboards";
import { useProjects } from "@/hooks/useProjects";

export interface PublishedViewCardProps {
  dashboard: DashboardRead;
}

export function PublishedViewCard({ dashboard }: PublishedViewCardProps) {
  const { t } = useTranslation(["dashboards", "common"]);
  const publish = useSetPublishedView(dashboard.id);
  // This initiative's projects, and only the columns a picker needs. Scoped
  // rather than filtered afterwards: a guild's whole project list is a longer
  // answer than this question has, and paging through it to find one
  // initiative's would be the wrong shape of request.
  const projects = useProjects({
    initiative_id: dashboard.initiative_id,
    slim: true,
  });
  const [adding, setAdding] = useState<string>("");

  const published: PublishTarget[] = useMemo(
    () =>
      dashboard.published_over.map((entry) => ({
        resource_type: entry.resource_type,
        resource_id: entry.resource_id,
      })),
    [dashboard.published_over]
  );

  // Only what the author can already open: the list is their own reach, and
  // the server refuses anything past it anyway.
  const offerable = useMemo(() => {
    const already = new Set(
      published
        .filter((entry) => entry.resource_type === "project")
        .map((entry) => entry.resource_id)
    );
    return (projects.data?.items ?? []).filter(
      (project) => project.initiative_id === dashboard.initiative_id && !already.has(project.id)
    );
  }, [projects.data, published, dashboard.initiative_id]);

  const nameOf = (entry: PublishTarget): string => {
    const project = (projects.data?.items ?? []).find((held) => held.id === entry.resource_id);
    return project?.name ?? `#${entry.resource_id}`;
  };

  const save = (next: PublishTarget[]) => publish.mutate(next);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("dashboards:published.title")}</CardTitle>
        <CardDescription>{t("dashboards:published.help")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {published.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("dashboards:published.empty")}</p>
        ) : (
          <ul className="space-y-2">
            {published.map((entry) => (
              <li
                key={`${entry.resource_type}:${entry.resource_id}`}
                className="flex items-center justify-between gap-2 rounded-md border p-2"
              >
                <span className="min-w-0 truncate text-sm">{nameOf(entry)}</span>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7 shrink-0"
                  aria-label={t("dashboards:published.stop")}
                  disabled={publish.isPending}
                  onClick={() =>
                    save(
                      published.filter(
                        (held) =>
                          !(
                            held.resource_type === entry.resource_type &&
                            held.resource_id === entry.resource_id
                          )
                      )
                    )
                  }
                >
                  <X className="h-4 w-4" />
                </Button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex items-center gap-2">
          <Select value={adding} onValueChange={setAdding}>
            <SelectTrigger className="h-9 flex-1" aria-label={t("dashboards:published.choose")}>
              <SelectValue placeholder={t("dashboards:published.choose")} />
            </SelectTrigger>
            <SelectContent>
              {offerable.map((project) => (
                <SelectItem key={project.id} value={String(project.id)}>
                  {project.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            size="sm"
            variant="outline"
            disabled={!adding || publish.isPending}
            onClick={() => {
              save([...published, { resource_type: "project", resource_id: Number(adding) }]);
              setAdding("");
            }}
          >
            <Plus className="mr-1 h-4 w-4" />
            {t("dashboards:published.add")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
