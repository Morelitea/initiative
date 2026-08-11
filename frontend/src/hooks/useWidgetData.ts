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

import type {
  ListTasksApiV1GGuildIdTasksGetParams,
  WidgetCatalog,
} from "@/api/generated/initiativeAPI.schemas";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useCalendarEntries } from "@/hooks/useCalendarEntries";
import { useCalendarsList } from "@/hooks/useCalendars";
import { useCounterGroup } from "@/hooks/useCounters";
import { useDocument } from "@/hooks/useDocuments";
import { useProjects } from "@/hooks/useProjects";
import { useTasks } from "@/hooks/useTasks";
import { useUserStats } from "@/hooks/useUserStats";
import type { WidgetData, WidgetSource } from "@/lib/widgets/dataShapes";
import {
  type CountBucket,
  countTasks,
  countTasksByProject,
  emptyDataFor,
  normalizeCalendarEntries,
  normalizeCounter,
  normalizeCounterGroup,
  normalizeMyStats,
  normalizeProjects,
  normalizeSheetRange,
  normalizeTasks,
} from "@/lib/widgets/normalize";

/** A normalized definition binding. Everything past `source` is the fetcher's
 *  to interpret — the backend deliberately does not re-declare these, so that
 *  each parameter lives with the code that consumes it. */
export interface WidgetBinding {
  source: WidgetSource;
  conditions?: unknown;
  initiative_id?: number | null;
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
}

export interface WidgetDataResult {
  data: WidgetData;
  isLoading: boolean;
  /** A binding whose ids the instance config has not filled in yet — the widget
   *  renders its own empty state rather than an error. */
  isUnbound: boolean;
}

const DAY = 86_400_000;
const DEFAULT_WINDOW_DAYS = 90;

/** Sources that need the task list. `task_counts` and the project progress
 *  columns are derived from those same rows rather than fetched again. */
const TASK_BACKED: WidgetSource[] = ["tasks", "task_counts", "projects"];

export function useWidgetData(binding: WidgetBinding): WidgetDataResult {
  const guildId = useActiveGuildId();
  const source = binding.source;

  const taskParams = useMemo<ListTasksApiV1GGuildIdTasksGetParams>(() => {
    const params: Record<string, unknown> = { page_size: 0 };
    if (binding.project_id) params.project_id = binding.project_id;
    if (binding.initiative_id) params.initiative_id = binding.initiative_id;
    // The filter DSL passes through verbatim — the parser owns its own limits,
    // and mirroring them here would mean maintaining them twice.
    if (binding.conditions) params.conditions = JSON.stringify(binding.conditions);
    return params as ListTasksApiV1GGuildIdTasksGetParams;
  }, [binding.project_id, binding.initiative_id, binding.conditions]);

  const window = useMemo(() => {
    const days = binding.window_days ?? DEFAULT_WINDOW_DAYS;
    const now = Date.now();
    return {
      start: new Date(now - days * DAY).toISOString(),
      end: new Date(now + days * DAY).toISOString(),
    };
  }, [binding.window_days]);

  const tasksQuery = useTasks(taskParams, {
    enabled: TASK_BACKED.includes(source),
  });
  // The projects list has no initiative filter of its own; a binding scoped to
  // one initiative narrows the rows after the fetch, which also keeps the query
  // key shared with every other projects consumer.
  const projectsQuery = useProjects(undefined, { enabled: source === "projects" });
  const entriesQuery = useCalendarEntries(
    {
      start_after: window.start,
      start_before: window.end,
      include_events: true,
      ...(binding.initiative_id ? { initiative_id: binding.initiative_id } : {}),
    },
    { enabled: source === "calendar_entries" }
  );
  const calendarsQuery = useCalendarsList(undefined, {
    enabled: source === "calendar_entries",
  });
  const counterGroupQuery = useCounterGroup(binding.counter_group_id ?? null, {
    enabled: source === "counter" || source === "counter_group",
  });
  const statsQuery = useUserStats(source === "my_stats" ? guildId : null);
  const documentQuery = useDocument(
    source === "sheet_range" ? (binding.document_id ?? null) : null
  );

  return useMemo<WidgetDataResult>(() => {
    const unbound = (): WidgetDataResult => ({
      data: emptyDataFor(source),
      isLoading: false,
      isUnbound: true,
    });

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
          (project) => !binding.initiative_id || project.initiative_id === binding.initiative_id
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
        const counter = counterGroupQuery.data?.counters?.find(
          (candidate) => candidate.id === binding.counter_id
        );
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
        if (!counterGroupQuery.data) {
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

      case "my_stats": {
        if (!statsQuery.data) {
          return {
            data: emptyDataFor(source),
            isLoading: statsQuery.isLoading,
            isUnbound: false,
          };
        }
        const { days, total } = normalizeMyStats(statsQuery.data);
        return { data: { source, days, total }, isLoading: false, isUnbound: false };
      }

      case "sheet_range": {
        if (!binding.document_id || !binding.range) return unbound();
        const range = documentQuery.data
          ? normalizeSheetRange(documentQuery.data, binding.sheet, binding.range)
          : null;
        if (!range) {
          return {
            data: emptyDataFor(source),
            isLoading: documentQuery.isLoading,
            isUnbound: !documentQuery.isLoading,
          };
        }
        return { data: { source, range }, isLoading: false, isUnbound: false };
      }

      default:
        return unbound();
    }
  }, [
    source,
    binding.bucket,
    binding.calendar_id,
    binding.counter_group_id,
    binding.counter_id,
    binding.document_id,
    binding.initiative_id,
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
    statsQuery.data,
    statsQuery.isLoading,
    documentQuery.data,
    documentQuery.isLoading,
  ]);
}

/** Sources this build can fetch, for the binding picker. Derived from the
 *  served catalog so it never disagrees with what the backend will accept. */
export const bindableSources = (catalog: WidgetCatalog | undefined, widgetType: string): string[] =>
  catalog?.widgets.find((entry) => entry.type === widgetType)?.sources ?? [];
