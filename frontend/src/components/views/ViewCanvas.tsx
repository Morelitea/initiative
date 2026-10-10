import { type MouseEvent, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  TaskListRead,
  TaskStatusRead,
  ToolViewWrite,
} from "@/api/generated/initiativeAPI.schemas";
import { ProjectTasksKanbanView } from "@/components/projects/ProjectTasksKanbanView";
import { ProjectTasksTableView } from "@/components/projects/ProjectTasksTableView";
import { type useProjectTaskTableState, viewTableSorting } from "@/hooks/useProjectTaskView";
import { useTasks } from "@/hooks/useTasks";
import { buildTaskListParams, specFromApi } from "@/lib/filters/taskFilters";
import { cardOf, indexPaths } from "@/lib/views/draft";

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

/**
 * The view being edited, drawn as its readers will see it, with the project's
 * own tasks. Nothing in it can be changed or opened: a click selects the part
 * it landed on, which the outline and the settings then show.
 */
export const ViewCanvas = ({
  projectId,
  initiativeId,
  statuses,
  view,
  width,
  selected,
  onSelect,
}: {
  projectId: number;
  initiativeId: number;
  statuses: TaskStatusRead[];
  view: ToolViewWrite;
  width: PreviewWidth;
  /** What the outline has selected, as `card:<path>` or `column:<field>`. */
  selected: string;
  onSelect: (selected: string) => void;
}) => {
  const { t } = useTranslation("projects");
  const [hovered, setHovered] = useState<string | null>(null);
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

  /** The part a pointer is over: the nearest marked one, named as the outline
   *  names it. */
  const partAt = (target: EventTarget): string | null => {
    const marked = target instanceof Element ? target.closest("[data-view-node]") : null;
    const node = marked?.getAttribute("data-view-node");
    if (node === null || node === undefined) return null;
    return node.startsWith("column:") ? node : `card:${node}`;
  };
  const marked = (name: string | null) => {
    if (!name) return null;
    const value = name.startsWith("card:") ? name.slice("card:".length) : name;
    return `[data-view-node=${quoted(value)}] > *`;
  };
  const selectedRule = marked(selected);
  const hoveredRule = hovered !== selected ? marked(hovered) : null;

  // Only what the outline can name is selectable; the rest of the page is
  // the page.
  const select = (event: MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
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
        onPointerDownCapture={(event) => {
          event.preventDefault();
          event.stopPropagation();
        }}
        onMouseOver={(event) => setHovered(partAt(event.target))}
        onFocus={(event) => setHovered(partAt(event.target))}
        onMouseLeave={() => setHovered(null)}
        aria-label={t("viewEditor.canvas")}
        role="region"
      >
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
      </div>
    </div>
  );
};

const NO_TASKS: TaskListRead[] = [];
const taskHref = () => "#";
