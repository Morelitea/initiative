/**
 * The item pages the view editor lays out: a project's task page, and the
 * initiative calendar's event page. Each says what kind of item it is, what
 * its fields are called and whether plug-ins draw on it, and draws itself with
 * one of its items while it is laid out.
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
import { buildTaskListParams, specFromApi } from "@/lib/filters/taskFilters";
import { EventPageView } from "@/lib/views/eventPage";
import { EVENT_PAGE_KIND, eventFields } from "@/lib/views/events";
import type { FieldDef } from "@/lib/views/fields";
import type { ItemPageKind, StoredRegions } from "@/lib/views/itemPage";
import { TaskPageView } from "@/lib/views/taskPage";
import { TASK_PAGE_KIND, taskFields } from "@/lib/views/tasks";
import type { ViewNode } from "@/lib/views/tree";

import type { ViewProject } from "./ViewSettingsPanel";

/** A kind of item's page, as the editor lays it out. */
export type EditablePage = {
  kind: ItemPageKind;
  /** What the editor says about it, as keys in `projects`: its name, what it
   *  is, that it is as shipped, and where the rest is said in its own words:
   *  its parts' names (`.parts`) and what each does (`.partHelp`), and what
   *  its title and its fields are (`.pageTitleHelp`, `.toMoreFieldsHelp`). */
  words: { name: string; help: string; shipped: string; own: string };
  /** What its "More fields" section is called, as a key naming its namespace. */
  moreFields: string;
  /** Its fields, by id: the built-ins, and the plug-ins' where they draw on it. */
  fields: (definitions: PropertyDefinitionRead[], plugins: FieldDef[]) => Map<string, FieldDef>;
  /** Whether plug-ins draw on it, so the editor offers their parts and fields. */
  plugins: boolean;
  /** The page drawn with one of its items, laid out as `page` says. */
  preview: (page: ViewNode) => ReactNode;
};

/** The page tree's regions, as a page view draws them. */
const regionsOf = (page: ViewNode): StoredRegions => ({
  header: page.children?.[0]?.children ?? [],
  main: page.children?.[1]?.children ?? [],
  side: page.children?.[2]?.children ?? [],
});

/** What the page's menu is drawn as, where nothing in it is used. */
const ActionsPreview = () => (
  <Button type="button" variant="outline" size="icon" tabIndex={-1} aria-hidden>
    <MoreHorizontal className="h-4 w-4" />
  </Button>
);

const noop = () => {};

/** The task page drawn with the project's first task. */
const TaskPagePreview = ({ project, page }: { project: ViewProject; page: ViewNode }) => {
  const { t } = useTranslation("projects");
  const { user } = useAuth();
  const scopePrompt = useScopePrompt();
  const leaving = useRef(true);
  const params = useMemo(
    () => ({ ...buildTaskListParams(specFromApi(null), { projectId: project.id }), page_size: 1 }),
    [project.id]
  );
  const listed = useTasks(params);
  const first = listed.data?.items[0]?.id ?? null;
  const task = useTask(first).data;
  const layout = useMemo(() => regionsOf(page), [page]);
  if (task) {
    return (
      <TaskPageView
        task={task}
        layout={layout}
        editing
        page={{
          readOnly: false,
          // Drawn here so it can be placed; a reader sees it only when they
          // cannot change the task.
          readOnlyMessage: t("viewEditor.noticePreview"),
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
    <p className="text-muted-foreground text-sm">{t("viewEditor.noTasks")}</p>
  ) : null;
};

const YEAR = 365 * 24 * 60 * 60 * 1000;

/** The event page drawn with the first of the initiative's events this year,
 *  on either side of today. */
const EventPagePreview = ({ initiativeId, page }: { initiativeId: number; page: ViewNode }) => {
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
  const layout = useMemo(() => regionsOf(page), [page]);
  if (event) {
    return (
      <EventPageView
        event={event}
        layout={layout}
        editing
        page={{
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
    <p className="text-muted-foreground text-sm">{t("viewEditor.noEvents")}</p>
  ) : null;
};

/** A project's task page. */
export const taskPage = (project: ViewProject): EditablePage => ({
  kind: TASK_PAGE_KIND,
  words: {
    name: "viewEditor.taskPage",
    help: "viewEditor.pageHelp",
    shipped: "viewEditor.shippedPage",
    own: "viewEditor",
  },
  moreFields: "tasks:edit.moreFields",
  fields: taskFields,
  plugins: true,
  preview: (page) => <TaskPagePreview project={project} page={page} />,
});

/** The initiative calendar's event page. */
export const eventPage = (initiativeId: number): EditablePage => ({
  kind: EVENT_PAGE_KIND,
  words: {
    name: "viewEditor.eventPage.name",
    help: "viewEditor.eventPage.help",
    shipped: "viewEditor.eventPage.shipped",
    own: "viewEditor.eventPage",
  },
  moreFields: "calendars:eventPage.moreFields",
  fields: eventFields,
  plugins: false,
  preview: (page) => <EventPagePreview initiativeId={initiativeId} page={page} />,
});
