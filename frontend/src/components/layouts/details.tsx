/**
 * The details the layout editor lays out: a project's task, and the initiative
 * calendar's event. Each says what kind of detail it is, what the editor calls
 * it and its parts, what its fields are, whether plug-ins draw on it, and
 * draws itself with one of its own while it is laid out.
 */

import { MoreHorizontal } from "lucide-react";
import { type ReactNode, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";

import type { PropertyDefinitionRead } from "@/api/generated/initiativeAPI.schemas";
import { useScopePrompt } from "@/components/recurrence/OccurrenceScopeDialog";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { useCalendarEntries } from "@/hooks/useCalendarEntries";
import { useCalendarEvent } from "@/hooks/useCalendarEvents";
import { useTask, useTasks } from "@/hooks/useTasks";
import { buildTaskListParams, EMPTY_TASK_FILTERS } from "@/lib/filters/taskFilters";
import type { DetailLayoutSpec, StoredRegions } from "@/lib/layouts/detailLayout";
import { EventLayoutView } from "@/lib/layouts/eventLayout";
import { EVENT_LAYOUT, eventFields } from "@/lib/layouts/events";
import type { FieldDef } from "@/lib/layouts/fields";
import { TaskLayoutView } from "@/lib/layouts/taskLayout";
import { TASK_LAYOUT, taskFields } from "@/lib/layouts/tasks";
import type { LayoutNode } from "@/lib/layouts/tree";

import type { LayoutProject } from "./LayoutSettingsPanel";

/** A kind of detail, as the editor lays it out. */
export type EditableDetail = {
  spec: DetailLayoutSpec;
  /** What the editor says about it, as keys in `projects`, each naming its
   *  namespace where it is another: its name, what it is, that it is as
   *  shipped, what its title and its fields are, and where its own parts'
   *  names (`.parts`) and what each does (`.partHelp`) are. */
  words: {
    name: string;
    help: string;
    shipped: string;
    titleHelp: string;
    toMoreFieldsHelp: string;
    moreFields: string;
    parts: string;
  };
  /** Its fields, by id: the built-ins, and the plug-ins' where they draw on it. */
  fields: (definitions: PropertyDefinitionRead[], plugins: FieldDef[]) => Map<string, FieldDef>;
  /** Whether plug-ins draw on it, so the editor offers their parts and fields. */
  plugins: boolean;
  /** The detail drawn with one of its own, laid out as `tree` says. */
  preview: (tree: LayoutNode) => ReactNode;
};

/** The detail tree's regions, as a detail draws them. */
const regionsOf = (tree: LayoutNode): StoredRegions => ({
  header: tree.children?.[0]?.children ?? [],
  main: tree.children?.[1]?.children ?? [],
  side: tree.children?.[2]?.children ?? [],
});

/** What a detail's menu is drawn as, where nothing in it is used. */
const ActionsPreview = () => (
  <Button type="button" variant="outline" size="icon" tabIndex={-1} aria-hidden>
    <MoreHorizontal className="h-4 w-4" />
  </Button>
);

const noop = () => {};

/** The task's detail drawn with the project's first task. */
const TaskPreview = ({ project, tree }: { project: LayoutProject; tree: LayoutNode }) => {
  const { t } = useTranslation("projects");
  const { user } = useAuth();
  const scopePrompt = useScopePrompt();
  const leaving = useRef(true);
  const params = useMemo(
    () => ({ ...buildTaskListParams(EMPTY_TASK_FILTERS, { projectId: project.id }), page_size: 1 }),
    [project.id]
  );
  const listed = useTasks(params);
  const first = listed.data?.items[0]?.id ?? null;
  const task = useTask(first).data;
  const layout = useMemo(() => regionsOf(tree), [tree]);
  if (task) {
    return (
      <TaskLayoutView
        task={task}
        layout={layout}
        editing
        context={{
          readOnly: false,
          // Drawn here so it can be placed; a reader sees it only when they
          // cannot change the task.
          readOnlyMessage: t("layoutEditor.noticePreview"),
          statuses: project.statuses,
          initiativeId: project.initiativeId,
          currentUserId: user?.id,
          askScope: scopePrompt.ask,
          actions: <ActionsPreview />,
          leaving,
          preview: true,
        }}
      />
    );
  }
  return listed.isSuccess && first === null ? (
    <p className="text-muted-foreground text-sm">{t("layoutEditor.noTasks")}</p>
  ) : null;
};

const YEAR = 365 * 24 * 60 * 60 * 1000;

/** The event's detail drawn with the first of the initiative's events within
 *  a year either side of today. */
const EventPreview = ({ initiativeId, tree }: { initiativeId: number; tree: LayoutNode }) => {
  const { t } = useTranslation("projects");
  const leaving = useRef(true);
  const params = useMemo(() => {
    const now = Date.now();
    return {
      initiative_id: initiativeId,
      include_tasks: false,
      start_after: new Date(now - YEAR).toISOString(),
      start_before: new Date(now + YEAR).toISOString(),
    };
  }, [initiativeId]);
  const listed = useCalendarEntries(params);
  const first = listed.data?.events[0]?.id ?? null;
  const event = useCalendarEvent(first).data;
  const layout = useMemo(() => regionsOf(tree), [tree]);
  if (event) {
    return (
      <EventLayoutView
        event={event}
        layout={layout}
        editing
        context={{
          readOnly: false,
          initiativeId,
          occurrence: undefined,
          occurrenceStart: event.start_at,
          shownStart: event.start_at,
          shownEnd: event.end_at,
          askScope: async () => null,
          onMoved: noop,
          onShifted: noop,
          leaving,
          actions: <ActionsPreview />,
          preview: true,
        }}
      />
    );
  }
  return listed.isSuccess && first === null ? (
    <p className="text-muted-foreground text-sm">{t("layoutEditor.noEvents")}</p>
  ) : null;
};

/** A project's task detail. */
export const taskDetail = (project: LayoutProject): EditableDetail => ({
  spec: TASK_LAYOUT,
  words: {
    name: "layoutEditor.taskLayout",
    help: "layoutEditor.detailHelp",
    shipped: "layoutEditor.shipped",
    titleHelp: "layoutEditor.detailTitleHelp",
    toMoreFieldsHelp: "layoutEditor.toMoreFieldsHelp",
    moreFields: "tasks:edit.moreFields",
    parts: "layoutEditor",
  },
  fields: taskFields,
  plugins: true,
  preview: (tree) => <TaskPreview project={project} tree={tree} />,
});

/** The initiative calendar's event detail. */
export const eventDetail = (initiativeId: number): EditableDetail => ({
  spec: EVENT_LAYOUT,
  words: {
    name: "layoutEditor.eventDetail.name",
    help: "layoutEditor.eventDetail.help",
    shipped: "layoutEditor.eventDetail.shipped",
    titleHelp: "layoutEditor.eventDetail.titleHelp",
    toMoreFieldsHelp: "layoutEditor.eventDetail.toMoreFieldsHelp",
    moreFields: "calendars:eventPage.moreFields",
    parts: "layoutEditor.eventDetail",
  },
  fields: eventFields,
  plugins: false,
  preview: (tree) => <EventPreview initiativeId={initiativeId} tree={tree} />,
});
