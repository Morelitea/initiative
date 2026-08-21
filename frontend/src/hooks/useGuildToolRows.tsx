/**
 * One guild-wide page of whatever tool the guild home is showing.
 *
 * The six list endpoints already agree on a shape — `{ items, total_count,
 * has_next }` keyed by `page`/`page_size` — so this hook calls all six and
 * gates every one but the selected tool with `enabled: false`. That keeps the
 * calls unconditional (hook rules) while exactly one request is in flight, and
 * leaves the tool switch as a plain `switch` whose exhaustiveness the compiler
 * checks: a new `Tool` member fails to build here until it can produce rows.
 */

import type { ReactNode } from "react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { ProgressCircle } from "@/components/ui/progress-circle";
import { useCalendarsList } from "@/hooks/useCalendars";
import { useCounterGroupsList } from "@/hooks/useCounters";
import { useDashboardsList } from "@/hooks/useDashboards";
import { useDocumentsList } from "@/hooks/useDocuments";
import { useProjects } from "@/hooks/useProjects";
import { useQueuesList } from "@/hooks/useQueues";
import { toolListRoute } from "@/lib/tools";

/** One row of the guild home table, in terms every tool can answer. */
export interface GuildToolRow {
  id: number;
  name: string;
  /** Guild-relative detail route, e.g. `/projects/12`. */
  href: string;
  /** Leading mark in the name cell — a project's emoji, a calendar's colour. */
  glyph: ReactNode;
  /** `null` for the guild-level rows a tool allows (calendars). */
  initiativeId: number | null;
  tags: TagSummary[];
  updatedAt: string;
  /** The tool's own column: what this row is, in its own terms. */
  detail: ReactNode;
  /** The scalar behind {@link detail}, so that column sorts. */
  detailSort: string | number;
}

const ColourDot = ({ colour }: { colour: string }) => (
  <span
    aria-hidden
    className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
    style={{ backgroundColor: colour }}
  />
);

export function useGuildToolRows(tool: Tool, page: number, pageSize: number) {
  const { t } = useTranslation("guildHome");

  const params = { page, page_size: pageSize };
  // Only the selected tool fetches; the rest stay mounted but idle.
  const only = (candidate: Tool) => ({ enabled: candidate === tool });

  const projects = useProjects(params, only(Tool.project));
  const documents = useDocumentsList(params, only(Tool.document));
  const queues = useQueuesList(params, only(Tool.queue));
  const counterGroups = useCounterGroupsList(params, only(Tool.counter_group));
  const calendars = useCalendarsList(params, only(Tool.calendar));
  const dashboards = useDashboardsList(params, only(Tool.dashboard));

  const query = {
    [Tool.project]: projects,
    [Tool.document]: documents,
    [Tool.queue]: queues,
    [Tool.counter_group]: counterGroups,
    [Tool.calendar]: calendars,
    [Tool.dashboard]: dashboards,
  }[tool];

  const rows = useMemo<GuildToolRow[]>(() => {
    const href = (id: number) => `${toolListRoute(tool)}/${id}`;
    switch (tool) {
      case Tool.project:
        return (projects.data?.items ?? []).map((project) => {
          const { completed, total } = project.task_summary;
          const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
          return {
            id: project.id,
            name: project.name,
            href: href(project.id),
            glyph: project.icon,
            initiativeId: project.initiative_id,
            tags: project.tags,
            updatedAt: project.updated_at,
            detail: (
              <span className="flex items-center gap-2">
                <ProgressCircle value={percent} className="h-6 w-6 shrink-0" />
                {t("detail.tasksDone", { completed, total })}
              </span>
            ),
            detailSort: percent,
          };
        });
      case Tool.document:
        return (documents.data?.items ?? []).map((document) => ({
          id: document.id,
          name: document.name,
          href: href(document.id),
          glyph: null,
          initiativeId: document.initiative_id,
          tags: document.tags,
          updatedAt: document.updated_at,
          detail: (
            <Badge variant="secondary">{t(`detail.documentType.${document.document_type}`)}</Badge>
          ),
          detailSort: document.document_type,
        }));
      case Tool.queue:
        return (queues.data?.items ?? []).map((queue) => ({
          id: queue.id,
          name: queue.name,
          href: href(queue.id),
          glyph: null,
          initiativeId: queue.initiative_id,
          tags: queue.tags,
          updatedAt: queue.updated_at,
          detail: t("detail.queueItems", { count: queue.item_count }),
          detailSort: queue.item_count,
        }));
      case Tool.counter_group:
        return (counterGroups.data?.items ?? []).map((group) => ({
          id: group.id,
          name: group.name,
          href: href(group.id),
          glyph: null,
          initiativeId: group.initiative_id,
          tags: group.tags,
          updatedAt: group.updated_at,
          detail: t("detail.counters", { count: group.counter_count }),
          detailSort: group.counter_count,
        }));
      case Tool.calendar:
        return (calendars.data?.items ?? []).map((calendar) => ({
          id: calendar.id,
          name: calendar.name,
          href: href(calendar.id),
          glyph: <ColourDot colour={calendar.color} />,
          initiativeId: calendar.initiative_id,
          tags: calendar.tags,
          updatedAt: calendar.updated_at,
          detail: calendar.description,
          detailSort: calendar.description ?? "",
        }));
      case Tool.dashboard:
        return (dashboards.data?.items ?? []).map((dashboard) => ({
          id: dashboard.id,
          name: dashboard.name,
          href: href(dashboard.id),
          glyph: null,
          initiativeId: dashboard.initiative_id,
          tags: dashboard.tags,
          updatedAt: dashboard.updated_at,
          detail: dashboard.listing_uid ? (
            <Badge variant="secondary">{t("detail.fromMarketplace")}</Badge>
          ) : (
            t("detail.builtHere")
          ),
          detailSort: dashboard.listing_uid ?? "",
        }));
    }
  }, [
    tool,
    t,
    projects.data,
    documents.data,
    queues.data,
    counterGroups.data,
    calendars.data,
    dashboards.data,
  ]);

  return {
    rows,
    totalCount: query.data?.total_count ?? 0,
    isLoading: query.isLoading,
    isError: query.isError,
  };
}
