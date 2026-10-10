import { MoreHorizontal } from "lucide-react";
import {
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
  type SyntheticEvent,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import type {
  TaskListRead,
  TaskStatusRead,
  ToolViewWrite,
} from "@/api/generated/initiativeAPI.schemas";
import { ProjectTasksKanbanView } from "@/components/projects/ProjectTasksKanbanView";
import { ProjectTasksTableView } from "@/components/projects/ProjectTasksTableView";
import { useScopePrompt } from "@/components/recurrence/OccurrenceScopeDialog";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { type useProjectTaskTableState, viewTableSorting } from "@/hooks/useProjectTaskView";
import { useTask, useTasks } from "@/hooks/useTasks";
import { buildTaskListParams, specFromApi } from "@/lib/filters/taskFilters";
import {
  cardOf,
  indexPaths,
  pathKey,
  pathOf,
  type Selection,
  sameSelection,
} from "@/lib/views/draft";
import { TaskPageView } from "@/lib/views/taskPage";
import type { ViewNode } from "@/lib/views/tree";

/** How wide the canvas draws the view: the widths a person might read it at. */
export type PreviewWidth = "desktop" | "tablet" | "phone";

const MAX_WIDTH: Record<PreviewWidth, string | undefined> = {
  desktop: undefined,
  tablet: "45rem",
  phone: "24rem",
};

const noop = () => {};
const NO_COLLAPSED = new Set<number>();

/** An attribute selector's quoted value. */
const quoted = (value: string) => `"${value.replace(/["\\]/g, "\\$&")}"`;

/** The part an element is in: the nearest marked one. A table marks its
 *  columns by field, and a tree its parts by path. */
const partAt = (target: EventTarget): Selection | null => {
  const marked = target instanceof Element ? target.closest("[data-view-node]") : null;
  const value = marked?.getAttribute("data-view-node");
  if (value === null || value === undefined) return null;
  return value.startsWith("column:")
    ? { kind: "column", field: value.slice("column:".length) }
    : { kind: "part", path: pathOf(value) };
};

const rule = (of: Selection | null) => {
  if (!of || of.kind === "view") return null;
  const value = of.kind === "column" ? `column:${of.field}` : pathKey(of.path);
  return `[data-view-node=${quoted(value)}] > *`;
};

/** Nothing on the canvas is used: a key, a paste or a drop goes nowhere. */
const refuse = (event: SyntheticEvent) => {
  event.preventDefault();
  event.stopPropagation();
};

/** Tab still moves focus on, so the canvas never holds it. */
const refuseKey = (event: KeyboardEvent) => {
  if (event.key !== "Tab") refuse(event);
};

/**
 * What is being edited, drawn as its readers will see it, at the width
 * chosen. Nothing in it can be changed or opened: a click selects the part it
 * landed on, which the outline and the settings then show, and keys, pastes
 * and drops are refused before what is drawn sees them.
 */
const CanvasFrame = ({
  width,
  selection,
  onSelect,
  children,
}: {
  width: PreviewWidth;
  selection: Selection;
  onSelect: (selection: Selection) => void;
  children: ReactNode;
}) => {
  const { t } = useTranslation("projects");
  const [hovered, setHovered] = useState<Selection | null>(null);
  const selectedRule = rule(selection);
  const hoveredRule = hovered && !sameSelection(hovered, selection) ? rule(hovered) : null;

  // Only what the outline can name is selectable; the rest of the page is
  // the page.
  const select = (event: MouseEvent) => {
    refuse(event);
    const part = partAt(event.target);
    if (part) onSelect(part);
  };

  return (
    <div className="h-full overflow-auto bg-muted/40 p-6">
      <style>
        {[
          selectedRule &&
            `${selectedRule} { outline: 2px solid var(--color-primary); outline-offset: 2px; border-radius: 0.25rem; }`,
          hoveredRule &&
            `${hoveredRule} { outline: 1px dashed var(--color-primary); outline-offset: 2px; border-radius: 0.25rem; }`,
        ]
          .filter(Boolean)
          .join("\n")}
      </style>
      <div
        className="@container mx-auto rounded-lg border bg-background p-4 shadow-sm"
        style={{ maxWidth: MAX_WIDTH[width] }}
        onClickCapture={select}
        onPointerDownCapture={refuse}
        onKeyDownCapture={refuseKey}
        onBeforeInputCapture={refuse}
        onPasteCapture={refuse}
        onDropCapture={refuse}
        onMouseOver={(event) => setHovered(partAt(event.target))}
        onFocus={(event) => setHovered(partAt(event.target))}
        onMouseLeave={() => setHovered(null)}
        aria-label={t("viewEditor.canvas")}
        role="region"
      >
        {children}
      </div>
    </div>
  );
};

/** The view being edited, with the project's own tasks. */
export const ViewCanvas = ({
  projectId,
  initiativeId,
  statuses,
  view,
  width,
  selection,
  onSelect,
}: {
  projectId: number;
  initiativeId: number;
  statuses: TaskStatusRead[];
  view: ToolViewWrite;
  width: PreviewWidth;
  selection: Selection;
  onSelect: (selection: Selection) => void;
}) => {
  const { t } = useTranslation("projects");
  const { definition } = view;
  const layout = definition.layout.type;
  const sorting = useMemo(() => viewTableSorting(view), [view]);
  const params = useMemo(
    () => buildTaskListParams(specFromApi(definition.filters), { projectId }),
    [definition.filters, projectId]
  );
  const tasks = useTasks(params).data?.items ?? NO_TASKS;

  const card = cardOf(definition);
  const paths = useMemo(() => indexPaths(card), [card]);
  const groupedTasks = useMemo(() => {
    const groups: Record<number, TaskListRead[]> = {};
    for (const status of statuses) groups[status.id] = [];
    for (const task of tasks) (groups[task.task_status_id] ??= []).push(task);
    return groups;
  }, [tasks, statuses]);
  // Sorted as the view is, and not remembered: the reader's own sort is theirs.
  const tableState = useMemo<ReturnType<typeof useProjectTaskTableState>>(
    () => [
      { grouping: [], sorting },
      { setGrouping: noop, setSorting: noop },
    ],
    [sorting]
  );

  return (
    <CanvasFrame width={width} selection={selection} onSelect={onSelect}>
      {layout === "board" ? (
        <ProjectTasksKanbanView
          projectId={projectId}
          initiativeId={initiativeId}
          taskStatuses={statuses}
          groupedTasks={groupedTasks}
          collapsedStatusIds={NO_COLLAPSED}
          canReorderTasks={false}
          taskHref={taskHref}
          sensors={undefined}
          activeTask={null}
          onDragStart={noop}
          onDragOver={noop}
          onDragEnd={noop}
          onDragCancel={noop}
          onToggleCollapse={noop}
          card={card}
          editing={paths}
        />
      ) : null}
      {layout === "table" ? (
        <ProjectTasksTableView
          key={JSON.stringify(sorting)}
          projectId={projectId}
          initiativeId={initiativeId}
          tasks={tasks}
          taskStatuses={statuses}
          sensors={undefined}
          canReorderTasks={false}
          canEditTaskDetails={false}
          taskActionsDisabled
          onDragStart={noop}
          onDragEnd={noop}
          onDragCancel={noop}
          onStatusChange={noop}
          taskHref={taskHref}
          tableState={tableState}
          viewColumns={definition.columns}
          editing
        />
      ) : null}
      {layout === "calendar" ? (
        <p className="text-muted-foreground text-sm">{t("viewEditor.calendarNote")}</p>
      ) : null}
    </CanvasFrame>
  );
};

/** The task page being laid out, drawn with one of the project's tasks. */
export const PageCanvas = ({
  projectId,
  initiativeId,
  statuses,
  page,
  width,
  selection,
  onSelect,
}: {
  projectId: number;
  initiativeId: number;
  statuses: TaskStatusRead[];
  /** The page as one tree: the page, holding its header, main and side. */
  page: ViewNode;
  width: PreviewWidth;
  selection: Selection;
  onSelect: (selection: Selection) => void;
}) => {
  const { t } = useTranslation("projects");
  const { user } = useAuth();
  const scopePrompt = useScopePrompt();
  const leaving = useRef(true);
  // One task to draw the page with: the project's first.
  const params = useMemo(
    () => ({ ...buildTaskListParams(specFromApi(null), { projectId }), page_size: 1 }),
    [projectId]
  );
  const listed = useTasks(params);
  const first = listed.data?.items[0]?.id ?? null;
  const task = useTask(first).data;
  const paths = useMemo(() => indexPaths(page), [page]);
  const layout = useMemo(
    () => ({
      header: page.children?.[0]?.children ?? [],
      main: page.children?.[1]?.children ?? [],
      side: page.children?.[2]?.children ?? [],
    }),
    [page]
  );

  return (
    <CanvasFrame width={width} selection={selection} onSelect={onSelect}>
      {task ? (
        <TaskPageView
          task={task}
          layout={layout}
          editing={paths}
          page={{
            readOnly: false,
            // Drawn here so it can be placed; a reader sees it only when they
            // cannot change the task.
            readOnlyMessage: t("viewEditor.noticePreview"),
            statuses,
            initiativeId,
            currentUserId: user?.id,
            askScope: scopePrompt.ask,
            actions: (
              <Button type="button" variant="outline" size="icon" tabIndex={-1} aria-hidden>
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            ),
            leaving,
            preview: true,
          }}
        />
      ) : listed.isSuccess && first === null ? (
        <p className="text-muted-foreground text-sm">{t("viewEditor.noTasks")}</p>
      ) : null}
    </CanvasFrame>
  );
};

const NO_TASKS: TaskListRead[] = [];
const taskHref = () => "#";
