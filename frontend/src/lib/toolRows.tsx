/**
 * One table row, in terms every tool can answer — and the one place a tool's
 * list response is turned into one.
 *
 * Two pages read the same table: a community's front page, showing one tool
 * across that community, and My Tools, showing one tool across every community
 * the reader belongs to. The rows are the same rows either way, so the mapping
 * lives here rather than in each page's hook: a new `Tool` member fails to
 * build in the `switch` below until it can produce them, and it then appears on
 * both pages at once.
 */

import type { TFunction } from "i18next";
import type { ReactNode } from "react";

import type {
  CalendarListResponse,
  CounterGroupListResponse,
  DashboardListResponse,
  DocumentListResponse,
  PostListResponse,
  ProjectListResponse,
  QueueListResponse,
  TagSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { ProgressCircle } from "@/components/ui/progress-circle";
import { toolDetailRoute } from "@/lib/tools";

/** One row of a tool table, in terms every tool can answer. */
export interface ToolRow {
  id: number;
  /** Which community the row lives in — what makes its address absolute. */
  guildId: number;
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

/**
 * A page of each tool's list, however the caller fetched it. Exactly one is
 * ever populated — the tool the table is showing — but the shape is stated for
 * every tool so the mapping below can be exhaustive over `Tool`.
 *
 * Every key is REQUIRED (and `undefined` is a legal value) so a caller
 * assembling one must name every tool. Optional keys let a new tool ship with
 * its entry simply missing: the table then asked for posts, got a response,
 * mapped it through a map that never mentioned them, and rendered "No results"
 * with nothing wrong anywhere the compiler could see.
 */
export type ToolResponses = {
  [Tool.project]: ProjectListResponse | undefined;
  [Tool.document]: DocumentListResponse | undefined;
  [Tool.queue]: QueueListResponse | undefined;
  [Tool.counter_group]: CounterGroupListResponse | undefined;
  [Tool.calendar]: CalendarListResponse | undefined;
  [Tool.dashboard]: DashboardListResponse | undefined;
  [Tool.post]: PostListResponse | undefined;
};

const ColourDot = ({ colour }: { colour: string }) => (
  <span
    aria-hidden
    className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
    style={{ backgroundColor: colour }}
  />
);

/**
 * Turn one tool's page of results into table rows.
 *
 * `fallbackGuildId` answers for a row whose payload leaves the community
 * unsaid — the guild-scoped lists, where every row is in the community the
 * page is already showing.
 */
export function buildToolRows(
  tool: Tool,
  data: ToolResponses,
  t: TFunction<"guildHome">,
  fallbackGuildId: number
): ToolRow[] {
  // Each row addresses its own initiative — a table spanning them (and, on My
  // Tools, spanning communities) needs the whole chain, not just the id.
  const href = (id: number, initiativeId: number | null) => toolDetailRoute(tool, initiativeId, id);

  switch (tool) {
    case Tool.project:
      return (data[Tool.project]?.items ?? []).map((project) => {
        const { completed, total } = project.task_summary;
        const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
        return {
          id: project.id,
          guildId: project.guild_id ?? project.initiative?.guild_id ?? fallbackGuildId,
          name: project.name,
          href: href(project.id, project.initiative_id),
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
      return (data[Tool.document]?.items ?? []).map((document) => ({
        id: document.id,
        guildId: document.guild_id ?? fallbackGuildId,
        name: document.name,
        href: href(document.id, document.initiative_id),
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
      return (data[Tool.queue]?.items ?? []).map((queue) => ({
        id: queue.id,
        guildId: queue.guild_id ?? fallbackGuildId,
        name: queue.name,
        href: href(queue.id, queue.initiative_id),
        glyph: null,
        initiativeId: queue.initiative_id,
        tags: queue.tags,
        updatedAt: queue.updated_at,
        detail: t("detail.queueItems", { count: queue.item_count }),
        detailSort: queue.item_count,
      }));
    case Tool.counter_group:
      return (data[Tool.counter_group]?.items ?? []).map((group) => ({
        id: group.id,
        guildId: group.guild_id ?? fallbackGuildId,
        name: group.name,
        href: href(group.id, group.initiative_id),
        glyph: null,
        initiativeId: group.initiative_id,
        tags: group.tags,
        updatedAt: group.updated_at,
        detail: t("detail.counters", { count: group.counter_count }),
        detailSort: group.counter_count,
      }));
    case Tool.calendar:
      return (data[Tool.calendar]?.items ?? []).map((calendar) => ({
        id: calendar.id,
        guildId: calendar.guild_id ?? fallbackGuildId,
        name: calendar.name,
        href: href(calendar.id, calendar.initiative_id),
        glyph: <ColourDot colour={calendar.color} />,
        initiativeId: calendar.initiative_id,
        tags: calendar.tags,
        updatedAt: calendar.updated_at,
        detail: calendar.description,
        detailSort: calendar.description ?? "",
      }));
    case Tool.dashboard:
      return (data[Tool.dashboard]?.items ?? []).map((dashboard) => ({
        id: dashboard.id,
        guildId: dashboard.guild_id ?? fallbackGuildId,
        name: dashboard.name,
        href: href(dashboard.id, dashboard.initiative_id),
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
    case Tool.post:
      return (data[Tool.post]?.items ?? []).map((post) => ({
        id: post.id,
        guildId: post.guild_id ?? fallbackGuildId,
        name: post.name,
        href: href(post.id, post.initiative_id),
        glyph: null,
        initiativeId: post.initiative_id,
        tags: post.tags,
        updatedAt: post.updated_at,
        // The first line of the notice. A table of posts is a table of
        // things people said, and the headline alone rarely distinguishes two
        // of them — the server derives this from the body for exactly here.
        detail: post.excerpt,
        detailSort: post.excerpt,
      }));
  }
}
