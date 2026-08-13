/**
 * Resolve a widget's binding into the data envelope it renders from.
 *
 * The security shape of this file matters more than its size. A binding names a
 * *source*, never an endpoint — and each source is fetched here through the same
 * ordinary hook the rest of the app uses, so the request is the viewer's own and
 * the six gates decide what comes back. A dashboard shared with someone who
 * cannot read the bound counter therefore shows them an empty widget, not the
 * author's data. Nothing a definition can say reaches a URL.
 *
 * Every source hook is called on every render with `enabled` gating rather than
 * conditionally, because hooks must be unconditional. Disabled queries cost
 * nothing, and the ones that do run share React Query's cache — two widgets
 * bound to the same tasks issue one request between them, which is what keeps a
 * dense canvas from becoming a request storm.
 */

import { useMemo } from "react";

import { resolveAppBinding } from "@/api/appData";
import type {
  ListTasksApiV1GGuildIdTasksGetParams,
  WidgetCatalog,
} from "@/api/generated/initiativeAPI.schemas";
import { useAppData, useAppWidgetCatalog } from "@/hooks/useAppData";
import { useCalendarEntries } from "@/hooks/useCalendarEntries";
import { useCalendarsList } from "@/hooks/useCalendars";
import { useCounterGroup } from "@/hooks/useCounters";
import { useDocument } from "@/hooks/useDocuments";
import { useProjects } from "@/hooks/useProjects";
import { useTasks } from "@/hooks/useTasks";
import type { WidgetData, WidgetSource } from "@/lib/widgets/dataShapes";
import { WidgetErrorCode } from "@/lib/widgets/errors";
import {
  type CountBucket,
  countTasks,
  countTasksByProject,
  emptyDataFor,
  normalizeCalendarEntries,
  normalizeCounter,
  normalizeCounterGroup,
  normalizeProjects,
  normalizeSheetRange,
  normalizeTasks,
} from "@/lib/widgets/normalize";

/** A normalized definition binding. Everything past `source` is the fetcher's
 *  to interpret — the backend deliberately does not re-declare these, so that
 *  each parameter lives with the code that consumes it.
 *
 *  The initiative is *not* among them: it comes from the dashboard the widget
 *  sits on, and the backend normalizer drops it from a stored binding. */
export interface WidgetBinding {
  source: WidgetSource;
  conditions?: unknown;
  project_id?: number | null;
  counter_group_id?: number | null;
  counter_id?: number | null;
  calendar_id?: number | null;
  document_id?: number | null;
  sheet?: string | null;
  range?: string | null;
  bucket?: CountBucket | null;
  /** Days back from today for time-windowed sources. */
  window_days?: number | null;
  /** `app` source: which installed app, which of its sources, and the arguments
   *  the source declared. The binding names a listing and a source id — never an
   *  address. Where the app lives comes from the deployment's registration, and
   *  only the server ever reads it. */
  app_uid?: string | null;
  source_id?: string | null;
  params?: Record<string, unknown> | null;
}

export interface WidgetDataResult {
  data: WidgetData;
  isLoading: boolean;
  /** A binding whose ids the instance config has not filled in yet — the widget
   *  renders its own empty state rather than an error. */
  isUnbound: boolean;
  /** Set when the tile should draw an error instead of running the widget. Only
   *  the `app` source produces one: our own sources fail closed to empty, but an
   *  external service being down is worth saying out loud. */
  errorCode?: WidgetErrorCode;
}

const DAY = 86_400_000;
const DEFAULT_WINDOW_DAYS = 90;

/** Sources that need the task list. `task_counts` and the project progress
 *  columns are derived from those same rows rather than fetched again. */
const TASK_BACKED: WidgetSource[] = ["tasks", "task_counts", "projects"];

/**
 * Resolve one widget's binding.
 *
 * `initiativeId` is the dashboard's own — every fetch below is scoped to it, and
 * a binding cannot say otherwise: dashboards are an initiative's tool, so a
 * widget reads that initiative and nothing else, exactly as a project board
 * reads its project. That holds three ways, all fail-closed:
 *
 * - without an initiative, nothing is fetched at all (unbound, not guild-wide);
 * - list sources carry the initiative in the query itself;
 * - id sources (a counter group, a document) are fetched by id and then held
 *   against the initiative — an id pointing into another one resolves to
 *   absent, the same rendering as a deleted or unshared target.
 *
 * `dashboardId` is the row the widget sits on, and only the `app` source needs
 * it: an app's data is guild-level, so the proxy is told which initiative-scoped
 * surface is asking and decides the read against *that* row's gates. Without it
 * — a preview, the picker — nothing is requested, exactly as without an
 * initiative.
 */
export function useWidgetData(
  binding: WidgetBinding,
  initiativeId: number | undefined,
  dashboardId?: number
): WidgetDataResult {
  const source = binding.source;
  const scoped = typeof initiativeId === "number" && Number.isFinite(initiativeId);

  /**
   * The task query, scoped through the filter DSL.
   *
   * `conditions` is the only narrowing the tasks endpoint reads — it has no
   * `initiative_id` or `project_id` query parameter — so the dashboard's
   * initiative and any bound project go in as conditions, AND-ed with the
   * binding's own.
   *
   * Flat, deliberately: the DSL caps group nesting, and the author's own
   * conditions may already use it, so adding a wrapper of our own would spend a
   * level they need. A top-level list is AND-ed anyway.
   */
  const taskParams = useMemo<ListTasksApiV1GGuildIdTasksGetParams>(() => {
    const conditions: unknown[] = [];
    if (initiativeId) {
      conditions.push({ field: "initiative_ids", op: "in_", value: [initiativeId] });
    }
    if (binding.project_id) {
      conditions.push({ field: "project_id", op: "eq", value: binding.project_id });
    }
    // The binding's own pass through verbatim — the parser owns its limits, and
    // mirroring them here would mean maintaining them twice. A definition may
    // carry either a list or a single group; the endpoint wants a list.
    const own = binding.conditions;
    if (Array.isArray(own)) conditions.push(...own);
    else if (own && typeof own === "object") conditions.push(own);

    const params: Record<string, unknown> = { page_size: 0 };
    if (conditions.length) params.conditions = JSON.stringify(conditions);
    return params as ListTasksApiV1GGuildIdTasksGetParams;
  }, [binding.project_id, initiativeId, binding.conditions]);

  const window = useMemo(() => {
    const days = binding.window_days ?? DEFAULT_WINDOW_DAYS;
    const now = Date.now();
    return {
      start: new Date(now - days * DAY).toISOString(),
      end: new Date(now + days * DAY).toISOString(),
    };
  }, [binding.window_days]);

  // Every query below is enabled only under `scoped`: with no initiative there
  // is nothing a dashboard widget may read, so nothing is requested.
  const tasksQuery = useTasks(taskParams, {
    enabled: scoped && TASK_BACKED.includes(source),
  });
  // The projects list has no initiative filter of its own, so its rows are
  // narrowed after the fetch — which also keeps the query key shared with every
  // other projects consumer.
  const projectsQuery = useProjects(undefined, { enabled: scoped && source === "projects" });
  const entriesQuery = useCalendarEntries(
    {
      start_after: window.start,
      start_before: window.end,
      include_events: true,
      initiative_id: initiativeId,
    },
    { enabled: scoped && source === "calendar_entries" }
  );
  const calendarsQuery = useCalendarsList(
    { initiative_id: initiativeId },
    { enabled: scoped && source === "calendar_entries" }
  );
  const counterGroupQuery = useCounterGroup(binding.counter_group_id ?? null, {
    enabled: scoped && (source === "counter" || source === "counter_group"),
  });
  const documentQuery = useDocument(
    scoped && source === "sheet_range" ? (binding.document_id ?? null) : null
  );

  // The app palette is one request per guild, shared by every app widget on the
  // canvas. It is what turns a binding's `app_uid` into an install id and tells
  // us what freshness the source asks for.
  const isApp = source === "app";
  const appCatalogQuery = useAppWidgetCatalog(scoped && isApp);
  const appBinding = resolveAppBinding(appCatalogQuery.data, binding.app_uid, binding.source_id);
  const appQuery = useAppData({
    appId: appBinding?.entry.app_id,
    sourceId: binding.source_id ?? undefined,
    dashboardId,
    params: binding.params ?? undefined,
    cacheTtlSeconds: appBinding?.source.cache_ttl_seconds,
    enabled: scoped && isApp,
  });

  return useMemo<WidgetDataResult>(() => {
    const unbound = (): WidgetDataResult => ({
      data: emptyDataFor(source),
      isLoading: false,
      isUnbound: true,
    });

    // No initiative, no data — fail closed rather than fan out.
    if (!scoped) return unbound();

    switch (source) {
      case "tasks": {
        const rows = normalizeTasks(tasksQuery.data?.items ?? []);
        return { data: { source, rows }, isLoading: tasksQuery.isLoading, isUnbound: false };
      }

      case "task_counts": {
        const rows = countTasks(
          normalizeTasks(tasksQuery.data?.items ?? []),
          binding.bucket ?? undefined
        );
        return { data: { source, rows }, isLoading: tasksQuery.isLoading, isUnbound: false };
      }

      case "projects": {
        const counts = countTasksByProject(normalizeTasks(tasksQuery.data?.items ?? []));
        const visible = (projectsQuery.data?.items ?? []).filter(
          (project) => !initiativeId || project.initiative_id === initiativeId
        );
        const rows = normalizeProjects(visible, counts);
        return {
          data: { source, rows },
          isLoading: projectsQuery.isLoading || tasksQuery.isLoading,
          isUnbound: false,
        };
      }

      case "calendar_entries": {
        const names = new Map<number, string>(
          (calendarsQuery.data?.items ?? []).map((calendar) => [calendar.id, calendar.name])
        );
        const events = (entriesQuery.data?.events ?? []).filter(
          (event) => !binding.calendar_id || event.calendar_id === binding.calendar_id
        );
        return {
          data: { source, rows: normalizeCalendarEntries(events, names) },
          isLoading: entriesQuery.isLoading,
          isUnbound: false,
        };
      }

      case "counter": {
        if (!binding.counter_group_id || !binding.counter_id) return unbound();
        // A group in another initiative resolves to absent, exactly like a
        // deleted or unshared one — bindings do not reach across initiatives.
        const group =
          counterGroupQuery.data?.initiative_id === initiativeId
            ? counterGroupQuery.data
            : undefined;
        const counter = group?.counters?.find((candidate) => candidate.id === binding.counter_id);
        if (!counter) {
          return {
            data: emptyDataFor(source),
            isLoading: counterGroupQuery.isLoading,
            // Resolved but absent: the counter was deleted, or RLS hid it.
            isUnbound: !counterGroupQuery.isLoading,
          };
        }
        return {
          data: { source, counter: normalizeCounter(counter) },
          isLoading: counterGroupQuery.isLoading,
          isUnbound: false,
        };
      }

      case "counter_group": {
        if (!binding.counter_group_id) return unbound();
        if (!counterGroupQuery.data || counterGroupQuery.data.initiative_id !== initiativeId) {
          return {
            data: emptyDataFor(source),
            isLoading: counterGroupQuery.isLoading,
            isUnbound: !counterGroupQuery.isLoading,
          };
        }
        const { name, counters } = normalizeCounterGroup(counterGroupQuery.data);
        return {
          data: { source, name, counters },
          isLoading: counterGroupQuery.isLoading,
          isUnbound: false,
        };
      }

      case "sheet_range": {
        if (!binding.document_id || !binding.range) return unbound();
        // Same rule as counter groups: a document outside this initiative is
        // absent, not readable.
        const document =
          documentQuery.data?.initiative_id === initiativeId ? documentQuery.data : undefined;
        const range = document ? normalizeSheetRange(document, binding.sheet, binding.range) : null;
        if (!range) {
          return {
            data: emptyDataFor(source),
            isLoading: documentQuery.isLoading,
            isUnbound: !documentQuery.isLoading,
          };
        }
        return { data: { source, range }, isLoading: false, isUnbound: false };
      }

      case "app": {
        // A definition that never had the app filled in, or a canvas with no
        // dashboard behind it (a preview). Neither is an error.
        if (!binding.app_uid || !binding.source_id || typeof dashboardId !== "number") {
          return unbound();
        }
        if (appCatalogQuery.isLoading) {
          return { data: emptyDataFor(source), isLoading: true, isUnbound: false };
        }
        // A catalog that failed to load says nothing about whether this app is
        // installed, so it must not be read as "not installed" — that would
        // render every app widget on the dashboard as unconfigured and invite
        // someone to repoint bindings that were never wrong.
        if (appCatalogQuery.isError) {
          return {
            data: emptyDataFor(source),
            isLoading: false,
            isUnbound: false,
            errorCode: WidgetErrorCode.APP_UNAVAILABLE,
          };
        }
        // The app is not installed in this guild, or its pinned version stopped
        // offering this source. Same rendering as a deleted counter: absent, not
        // broken — nothing here is the app's fault.
        if (!appBinding) {
          return { data: emptyDataFor(source), isLoading: false, isUnbound: true };
        }
        // An app that stopped answering does not blank a tile that already has
        // rows: React Query keeps the last good body for this key, and showing
        // it is more useful than showing nothing. The error tile is for when
        // there is genuinely nothing to draw.
        if (appQuery.isError && !appQuery.data) {
          return {
            data: emptyDataFor(source),
            isLoading: false,
            isUnbound: false,
            errorCode: WidgetErrorCode.APP_UNAVAILABLE,
          };
        }
        return {
          // Verbatim. Nothing on this side reads inside an app's rows; the
          // sandbox is handed them as values.
          data: { source, rows: appQuery.data?.rows ?? [] },
          isLoading: appQuery.isLoading,
          isUnbound: false,
        };
      }

      default:
        return unbound();
    }
  }, [
    source,
    initiativeId,
    binding.bucket,
    binding.calendar_id,
    binding.counter_group_id,
    binding.counter_id,
    binding.document_id,
    binding.range,
    binding.sheet,
    tasksQuery.data,
    tasksQuery.isLoading,
    projectsQuery.data,
    projectsQuery.isLoading,
    entriesQuery.data,
    entriesQuery.isLoading,
    calendarsQuery.data,
    counterGroupQuery.data,
    counterGroupQuery.isLoading,
    documentQuery.data,
    documentQuery.isLoading,
    scoped,
    dashboardId,
    binding.app_uid,
    binding.source_id,
    appBinding,
    appCatalogQuery.isLoading,
    appCatalogQuery.isError,
    appQuery.data,
    appQuery.isLoading,
    appQuery.isError,
  ]);
}

/** Sources this build can fetch, for the binding picker. Derived from the
 *  served catalog so it never disagrees with what the backend will accept. */
export const bindableSources = (catalog: WidgetCatalog | undefined, widgetType: string): string[] =>
  catalog?.widgets.find((entry) => entry.type === widgetType)?.sources ?? [];
