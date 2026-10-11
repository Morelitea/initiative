import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { useLexicalEditable } from "@lexical/react/useLexicalEditable";
import { keepPreviousData } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { $getNodeByKey, type NodeKey } from "lexical";
import { ChevronDown, ListChecks } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { EmbedSettingsButton } from "@/components/ui/editor/nodes/embed-settings-button";
import { $isReferenceEmbedNode } from "@/components/ui/editor/nodes/reference-embed-node";
import { Skeleton } from "@/components/ui/skeleton";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useProperties } from "@/hooks/useProperties";
import { useTasks } from "@/hooks/useTasks";
import { communityPath } from "@/lib/communityUrl";
import { EMBED_PAGE_SIZE, type EmbedDisplay, type TaskQuery, taskQueryParams } from "@/lib/embeds";
import { numberFormat } from "@/lib/intl";
import { fieldColumn } from "@/lib/layouts/columns";
import { useProjectLayoutEnv } from "@/lib/layouts/fields";
import { pluginFields, usePluginsOnItems } from "@/lib/layouts/plugins";
import { TASK_COLUMNS, taskFields } from "@/lib/layouts/tasks";
import { entityRefRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

interface TaskQueryEmbedProps {
  query: TaskQuery;
  display: EmbedDisplay;
  /** What its author called it. */
  label: string;
  collapsed: boolean;
  nodeKey: NodeKey;
}

/**
 * The tasks a filter matches, as a list, a table or a count.
 *
 * Read through the same task list every project page reads, as the person
 * looking: each reader sees the tasks they may open, `me` is them, and a due
 * window is counted from today. The list is kept current by the same signal
 * that refreshes a project's board, and it pages rather than stopping short.
 */
export function TaskQueryEmbed({ query, display, label, collapsed, nodeKey }: TaskQueryEmbedProps) {
  const { t, i18n } = useTranslation(["editor", "common"]);
  const [editor] = useLexicalComposerContext();
  const editable = useLexicalEditable();
  const communityId = useActiveCommunityId();
  const [page, setPage] = useState(1);
  const [readerFolded, setReaderFolded] = useState<boolean | null>(null);
  const folded = editable ? collapsed : (readerFolded ?? collapsed);
  const counting = display.mode === "count";
  // Rendering again at midnight is what rebuilds a due window from the new day.
  useLocalDay(query.filters.due !== null);

  const { data, isLoading, isError, isPlaceholderData, refetch } = useTasks(
    taskQueryParams(query, page, counting),
    {
      placeholderData: keepPreviousData,
    }
  );
  const tasks = data?.items ?? [];
  const total = data?.total_count ?? 0;

  // Fewer pages than the reader was on — something finished or was moved
  // while they looked — and the server answers with its last page: follow it.
  useEffect(() => {
    if (data && !isPlaceholderData && !counting && data.page !== page) setPage(data.page);
  }, [data, isPlaceholderData, counting, page]);

  const taskHref = useCallback(
    (taskId: number) => communityPath(communityId, entityRefRoute("task", taskId)),
    [communityId]
  );

  const toggleFolded = () => {
    if (!editable) {
      setReaderFolded(!folded);
      return;
    }
    editor.update(() => {
      const node = $getNodeByKey(nodeKey);
      if ($isReferenceEmbedNode(node)) node.setCollapsed(!folded);
    });
  };

  return (
    <>
      <span className="callout-icon" aria-hidden="true" />
      <div className="callout-body space-y-2">
        <div className="flex items-start gap-2">
          <ListChecks className="mt-1 size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 font-semibold">
            {label || t("embeds.tasks.untitled")}
          </span>
          {counting ? null : (
            <span className="shrink-0 pt-0.5 text-muted-foreground text-xs">
              {t("embeds.tasks.total", { count: total })}
            </span>
          )}
          {editable ? <EmbedSettingsButton nodeKey={nodeKey} /> : null}
          {counting ? null : (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="-my-1 size-7 shrink-0"
              onClick={toggleFolded}
              aria-expanded={!folded}
              aria-label={t(folded ? "embeds.expand" : "embeds.collapse")}
              title={t(folded ? "embeds.expand" : "embeds.collapse")}
            >
              <ChevronDown className={cn("size-4 transition-transform", folded && "-rotate-90")} />
            </Button>
          )}
        </div>
        {isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : isError && !data ? (
          <div className="flex items-center gap-2 text-muted-foreground text-sm">
            <span>{t("embeds.tasks.error")}</span>
            <Button type="button" variant="ghost" size="sm" onClick={() => void refetch()}>
              {t("common:tryAgain")}
            </Button>
          </div>
        ) : counting ? (
          <p className="font-semibold text-3xl tabular-nums">
            {numberFormat(i18n.language).format(total)}
          </p>
        ) : folded ? null : tasks.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("embeds.tasks.none")}</p>
        ) : display.mode === "table" ? (
          <TaskTable
            query={query}
            columns={display.columns}
            tasks={tasks}
            taskHref={taskHref}
            page={page}
            total={total}
            onPage={setPage}
          />
        ) : (
          <TaskList tasks={tasks} taskHref={taskHref} page={page} total={total} onPage={setPage} />
        )}
      </div>
    </>
  );
}

/** Today, as a number that changes at local midnight — while `watch` is on,
 *  so a page left open over midnight renders, and asks, for the new day. */
function useLocalDay(watch: boolean): number {
  const [day, setDay] = useState(() => new Date().setHours(0, 0, 0, 0));
  useEffect(() => {
    if (!watch) return;
    const next = new Date(day);
    next.setDate(next.getDate() + 1);
    const timer = setTimeout(
      () => setDay(new Date().setHours(0, 0, 0, 0)),
      Math.max(0, next.getTime() - Date.now()) + 1_000
    );
    return () => clearTimeout(timer);
  }, [watch, day]);
  return day;
}

interface PagedProps {
  page: number;
  total: number;
  onPage: (page: number) => void;
}

/** The tasks as lines: each its name, which opens it, and where it stands. */
function TaskList({
  tasks,
  taskHref,
  page,
  total,
  onPage,
}: PagedProps & { tasks: TaskListRead[]; taskHref: (taskId: number) => string }) {
  const { t } = useTranslation("editor");
  const pages = Math.max(1, Math.ceil(total / EMBED_PAGE_SIZE));
  return (
    <div className="space-y-2">
      <ul className="space-y-1">
        {tasks.map((task) => (
          <li key={task.id} className="flex items-baseline gap-2">
            <Link to={taskHref(task.id)} className="min-w-0 truncate font-medium hover:underline">
              {task.title}
            </Link>
            {task.task_status ? (
              <span className="shrink-0 text-muted-foreground text-xs">
                {task.task_status.name}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
      {pages > 1 ? (
        <div className="flex items-center gap-2 text-muted-foreground text-xs">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={page <= 1}
            onClick={() => onPage(page - 1)}
          >
            {t("embeds.tasks.previous")}
          </Button>
          <span>{t("embeds.tasks.page", { page, pages })}</span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={page >= pages}
            onClick={() => onPage(page + 1)}
          >
            {t("embeds.tasks.next")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/** The tasks as a table, with the columns its author chose — the same columns,
 *  drawn the same way, as a project's table. */
function TaskTable({
  query,
  columns: chosen,
  tasks,
  taskHref,
  page,
  total,
  onPage,
}: PagedProps & {
  query: TaskQuery;
  columns: string[] | undefined;
  tasks: TaskListRead[];
  taskHref: (taskId: number) => string;
}) {
  const { i18n } = useTranslation();
  const env = useProjectLayoutEnv(taskHref);
  const { data: definitions = [] } = useProperties({ initiativeId: query.initiative_id });
  const plugins = usePluginsOnItems(query.initiative_id);
  const fields = useMemo(
    () => taskFields(definitions, pluginFields(plugins, i18n.language)),
    [definitions, plugins, i18n.language]
  );
  const columns = useMemo(
    () =>
      (chosen ?? TASK_COLUMNS).flatMap((id) => {
        const field = fields.get(id);
        return field ? [fieldColumn<TaskListRead>(field, env)] : [];
      }),
    [chosen, fields, env]
  );
  return (
    <DataTable
      columns={columns}
      data={tasks}
      getRowId={(task) => String(task.id)}
      enablePagination
      manualPagination
      pageSizeOptions={[EMBED_PAGE_SIZE]}
      pageIndex={page - 1}
      pageCount={Math.max(1, Math.ceil(total / EMBED_PAGE_SIZE))}
      rowCount={total}
      onPaginationChange={(next) => onPage(next.pageIndex + 1)}
    />
  );
}
