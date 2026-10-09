import { useBlocker } from "@tanstack/react-router";
import { format } from "date-fns";
import { Loader2, Sparkles, X } from "lucide-react";
import {
  type ComponentType,
  createContext,
  type ReactNode,
  type RefObject,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import {
  type PropertyDefinitionRead,
  type PropertySummary,
  SearchEntityType,
  type TagSummary,
  type TaskPriority,
  type TaskRead,
  type TaskStatusRead,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { CommentSection } from "@/components/comments/CommentSection";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import { MentionComposer } from "@/components/markdown/MentionComposer";
import { MemberMultiSelect } from "@/components/members/MemberSearchSelect";
import { AddPropertyButton } from "@/components/properties/AddPropertyButton";
import { propertyStubFromDefinition } from "@/components/properties/PropertyFields";
import { PropertyInput } from "@/components/properties/PropertyInput";
import {
  isEmptyPropertyValue,
  normalizePropertyValue,
  userReferenceValue,
} from "@/components/properties/propertyHelpers";
import type { useScopePrompt } from "@/components/recurrence/OccurrenceScopeDialog";
import { RecurrenceEditor } from "@/components/recurrence/RecurrenceEditor";
import { TagPicker } from "@/components/tags";
import { TaskChecklist } from "@/components/tasks/TaskChecklist";
import { TaskDescription } from "@/components/tasks/TaskDescription";
import { TaskPriorityOption } from "@/components/tasks/TaskPriorityOption";
import { statusTriggerStyle, TaskStatusOption } from "@/components/tasks/TaskStatusOption";
import { CasePanel } from "@/components/tickets/CasePanel";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAIEnabled } from "@/hooks/useAIEnabled";
import { useComments, useCommentsCache } from "@/hooks/useComments";
import { useDateLocale } from "@/hooks/useDateLocale";
import { usePastedImages } from "@/hooks/usePastedImages";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import { type TaskEdit, useGenerateTaskDescription, useTaskFieldSave } from "@/hooks/useTasks";
import { useCommunityPath } from "@/lib/communityUrl";
import { dateRangeBounds } from "@/lib/dateRange";
import { getHttpStatus } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { currentServerKey } from "@/lib/offlineSession";
import { fromStored, type RecurrenceRule, rulePayload } from "@/lib/recurrence";
import { referenceRef } from "@/lib/smartChips";
import { PRIORITY_ORDER } from "@/lib/sorting";
import { getItem, removeItem, setItem } from "@/lib/storage";
import { dateTimePattern } from "@/lib/timeFormat";
import { taskRoute } from "@/lib/tools";
import {
  getAvatarSrc,
  getInitialsForUser,
  getUserDisplayName,
  isAnonymizedUser,
} from "@/lib/userDisplay";

import { FieldFrame, useFieldDraft } from "./editing";
import { type FieldKind, useProjectViewEnv } from "./fields";
import { TASK_PAGE, taskFields } from "./tasks";
import { LAYOUT_PARTS, type Parts, renderNode, type ViewContext } from "./tree";

/** What the task's page shares with its parts, beside the task itself. */
export interface TaskPageContext {
  /** The server says the reader cannot change the task. */
  readOnly: boolean;
  /** Why, when it does. */
  readOnlyMessage: string | null;
  /** The project's statuses, which the task's own joins when the project dropped it. */
  statuses: TaskStatusRead[];
  initiativeId: number | null;
  currentUserId?: number;
  askScope: ReturnType<typeof useScopePrompt>["ask"];
  /** The overflow menu of what else can be done with the task. */
  actions: ReactNode;
  /** Set when the page is left on purpose, so an open draft does not hold it. */
  leaving: RefObject<boolean>;
}

const PageContext = createContext<TaskPageContext | null>(null);

const useTaskPage = (): TaskPageContext => {
  const page = useContext(PageContext);
  if (!page) throw new Error("A task page part is drawn outside its page");
  return page;
};

type EditorProps = { task: TaskRead; label: string };

const sameJson = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** The task's title, which is the page's heading. */
const TitleEditor = ({ task, label }: EditorProps) => {
  const { t } = useTranslation("tasks");
  const { readOnly, askScope } = useTaskPage();
  const save = useTaskFieldSave(task, label, askScope);
  // A title cannot be emptied: leaving it blank puts the saved one back.
  const draft = useFieldDraft(task.title, async (title) =>
    title.trim() ? save.save({ patch: { title }, shows: { title } }) : false
  );
  return (
    <FieldFrame
      label={label}
      htmlFor="task-title"
      hideLabel
      save={save}
      changed={draft.changed}
      keys={draft.keys}
      className="flex-1"
    >
      <h1 className="sr-only">{task.title}</h1>
      <Input
        id="task-title"
        value={draft.value}
        onChange={(event) => draft.change(event.target.value)}
        placeholder={t("taskForm.titlePlaceholder")}
        disabled={readOnly}
        className="h-auto font-semibold text-3xl tracking-tight shadow-none focus-visible:ring-0 sm:text-3xl"
      />
    </FieldFrame>
  );
};

/** The preview of a description being edited reads the way the saved one will. */
const renderDescription = (draft: string) => <TaskDescription content={draft} />;

/** A description being written, and the one it was written over. */
interface DescriptionDraft {
  text: string;
  base: string | null;
}

/** Each account on each server keeps its own drafts on a shared device. */
const descriptionDraftKey = (userId: number | undefined, communityId: number, taskId: number) =>
  `task-description-draft:${userId}@${currentServerKey()}:${communityId}:${taskId}`;

const readDescriptionDraft = (key: string): DescriptionDraft | null => {
  try {
    const stored = JSON.parse(getItem(key) ?? "null") as DescriptionDraft | null;
    return stored && typeof stored.text === "string" ? stored : null;
  } catch {
    return null;
  }
};

/**
 * The description, edited in a mode the reader opens and saved only with
 * Save (or Ctrl/Cmd+Enter). The draft is kept on the device until it is saved
 * or discarded. The save names the description it was written over, and one
 * written over a description that has since changed is refused, so the reader
 * sees the other version and chooses.
 */
const DescriptionEditor = ({ task, label }: EditorProps) => {
  const { t } = useTranslation(["tasks", "common"]);
  const { readOnly, initiativeId, currentUserId, leaving, askScope } = useTaskPage();
  const communityId = useActiveCommunityId();
  const uploadImage = usePastedImages();
  const { isEnabled: aiEnabled } = useAIEnabled();
  // Saved by Save or by Retry. What was typed while it saved stays the draft,
  // now written over the description just saved.
  const save = useTaskFieldSave(task, label, askScope, ({ shows }) => {
    const now = latest.current;
    const saved = shows.description ?? null;
    if (now) setDraft(now.text === (saved ?? "") ? null : { ...now, base: saved });
  });
  const key = descriptionDraftKey(currentUserId, communityId, task.id);
  const [draft, setDraftState] = useState(() => readDescriptionDraft(key));
  const [discarding, setDiscarding] = useState(false);
  // Read by the description written for the reader, which lands later.
  const latest = useRef(draft);

  const setDraft = (next: DescriptionDraft | null) => {
    latest.current = next;
    setDraftState(next);
    void (next ? setItem(key, JSON.stringify(next)) : removeItem(key));
    // A refused save belongs to the draft, and goes with it.
    if (!next) save.reset();
  };

  const generate = useGenerateTaskDescription({
    onSuccess: (data) => {
      setDraft({ text: data.description, base: latest.current?.base ?? task.description });
      toast.success(t("edit.descriptionGenerated"));
    },
  });

  const current = task.description ?? "";
  const conflict = draft !== null && getHttpStatus(save.error) === 409;
  const dirty = draft !== null && draft.text !== (draft.base ?? "");
  const blocker = useBlocker({
    shouldBlockFn: () => dirty && !leaving.current,
    enableBeforeUnload: () => dirty && !leaving.current,
    withResolver: true,
  });

  const submit = (base: string | null) => {
    if (!draft) return;
    const description = draft.text || null;
    void save.save({ patch: { description, description_base: base }, shows: { description } });
  };
  const cancel = () => (dirty ? setDiscarding(true) : setDraft(null));

  return (
    <FieldFrame
      label={label}
      htmlFor="task-description"
      // The conflict below says what went wrong, and Retry would only repeat it.
      save={conflict ? { ...save, state: "idle" } : save}
      changed={
        draft !== null && !conflict && save.state !== "saving" && current !== (draft.base ?? "")
      }
      action={
        draft === null && !readOnly ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-xs"
            onClick={() => setDraft({ text: current, base: task.description })}
          >
            {t("common:edit")}
          </Button>
        ) : null
      }
    >
      {draft === null ? (
        current ? (
          <div className="rounded-md border border-border/70 border-dashed bg-muted/40 px-3 py-2">
            <TaskDescription content={current} />
          </div>
        ) : (
          <p className="text-muted-foreground text-sm italic">{t("edit.noDescriptionReadOnly")}</p>
        )
      ) : (
        <div className="space-y-2">
          <MentionComposer
            id="task-description"
            value={draft.text}
            onChange={(text) => setDraft({ ...draft, text })}
            initiativeId={initiativeId ?? 0}
            subject={referenceRef(SearchEntityType.task, task.id)}
            renderPreview={renderDescription}
            onUploadImage={uploadImage}
            placeholder={t("edit.descriptionPlaceholder")}
            autoFocus
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                submit(draft.base);
              } else if (event.key === "Escape") {
                event.preventDefault();
                cancel();
              }
            }}
            actions={
              aiEnabled ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-8 px-2 text-xs"
                  onClick={() => generate.mutate(task.id)}
                  disabled={generate.isPending}
                >
                  {generate.isPending ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Sparkles className="h-3 w-3" />
                  )}
                  {t("edit.aiGenerate")}
                </Button>
              ) : null
            }
          />
          {conflict ? (
            <div
              role="alert"
              className="space-y-2 rounded-md border border-warning/40 bg-warning/5 px-3 py-2"
            >
              <p className="text-sm">{t("common:fieldSave.changed")}</p>
              <div className="rounded-md border bg-background px-3 py-2">
                <TaskDescription content={current} />
              </div>
              <div className="flex flex-wrap gap-2">
                <Button type="button" size="sm" onClick={() => submit(task.description)}>
                  {t("common:fieldSave.overwrite")}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    save.reset();
                    setDraft({ ...draft, base: task.description });
                  }}
                >
                  {t("common:fieldSave.keepEditing")}
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                disabled={save.state === "saving"}
                onClick={() => submit(draft.base)}
              >
                {t("common:save")}
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={cancel}>
                {t("common:cancel")}
              </Button>
            </div>
          )}
        </div>
      )}
      <ConfirmDialog
        open={discarding}
        onOpenChange={setDiscarding}
        title={t("edit.unsavedTitle")}
        confirmLabel={t("common:fieldSave.discard")}
        cancelLabel={t("common:fieldSave.keepEditing")}
        onConfirm={() => {
          setDiscarding(false);
          setDraft(null);
        }}
        destructive
      />
      <ConfirmDialog
        open={blocker.status === "blocked"}
        onOpenChange={(open) => {
          if (!open) blocker.reset?.();
        }}
        title={t("edit.unsavedTitle")}
        description={t("edit.unsavedBody")}
        confirmLabel={t("edit.unsavedLeave")}
        cancelLabel={t("edit.unsavedStay")}
        onConfirm={() => {
          setDraft(null);
          blocker.proceed?.();
        }}
        destructive
      />
    </FieldFrame>
  );
};

const StatusEditor = ({ task }: { task: TaskRead }) => {
  const { t } = useTranslation("tasks");
  const { readOnly, statuses, askScope } = useTaskPage();
  const label = t("taskForm.statusLabel");
  const save = useTaskFieldSave(task, label, askScope);
  // A task keeps the status it was given after the project drops it, and the
  // select can only name a status it lists.
  const options = statuses.some((status) => status.id === task.task_status_id)
    ? statuses
    : [...statuses, task.task_status];
  const edit = (status: TaskStatusRead): TaskEdit => ({
    patch: { task_status_id: status.id },
    shows: { task_status_id: status.id, task_status: status },
  });
  return (
    <FieldFrame label={label} htmlFor="task-status" save={save}>
      <Select
        value={String(task.task_status_id)}
        onValueChange={(selected) => {
          const next = options.find((status) => String(status.id) === selected);
          if (next && next.id !== task.task_status_id) {
            void save.save(edit(next), edit(task.task_status));
          }
        }}
        disabled={readOnly}
      >
        <SelectTrigger
          id="task-status"
          className="border-2"
          style={statusTriggerStyle(task.task_status)}
        >
          <TaskStatusOption status={task.task_status} />
        </SelectTrigger>
        <SelectContent>
          {options.map((status) => (
            <SelectItem key={status.id} value={String(status.id)}>
              <TaskStatusOption status={status} />
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FieldFrame>
  );
};

const PriorityEditor = ({ task, label }: EditorProps) => {
  const { t } = useTranslation("tasks");
  const { readOnly, askScope } = useTaskPage();
  const save = useTaskFieldSave(task, label, askScope);
  return (
    <FieldFrame label={label} htmlFor="task-priority" save={save}>
      <Select
        value={task.priority}
        onValueChange={(selected) => {
          const priority = selected as TaskPriority;
          void save.save({ patch: { priority }, shows: { priority } });
        }}
        disabled={readOnly}
      >
        <SelectTrigger id="task-priority">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {PRIORITY_ORDER.map((option) => (
            <SelectItem key={option} value={option}>
              <TaskPriorityOption priority={option} label={t(`priority.${option}` as never)} />
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FieldFrame>
  );
};

const sameIds = (a: number[], b: number[]) => sameJson([...a].sort(), [...b].sort());

const AssigneesEditor = ({ task, label }: EditorProps) => {
  const { t } = useTranslation("tasks");
  const { readOnly, currentUserId, askScope } = useTaskPage();
  const save = useTaskFieldSave(task, label, askScope);
  const saved = task.assignees.map((assignee) => assignee.id);
  // Who is added shows from the draft until the task comes back naming them.
  const edit = (ids: number[]): TaskEdit => ({
    patch: { assignee_ids: ids },
    shows: { assignees: task.assignees.filter((assignee) => ids.includes(assignee.id)) },
  });
  const draft = useFieldDraft(
    saved,
    (ids) =>
      save.save(
        edit(ids),
        ids.length === 0
          ? { patch: { assignee_ids: saved }, shows: { assignees: task.assignees } }
          : undefined
      ),
    sameIds
  );
  return (
    <FieldFrame label={label} save={save}>
      <MemberMultiSelect
        scope={{ type: "canOpen", tool: Tool.project, id: task.project_id }}
        selectedIds={draft.value}
        selectedUsers={task.assignees}
        onChange={draft.edit}
        disabled={readOnly}
        emptyMessage={t("taskForm.assigneesEmptyMessage")}
        currentUserId={currentUserId}
      />
    </FieldFrame>
  );
};

const TagsEditor = ({ task, label }: EditorProps) => {
  const { t } = useTranslation("tasks");
  const { readOnly, askScope } = useTaskPage();
  const save = useTaskFieldSave(task, label, askScope);
  const edit = (tags: TagSummary[]): TaskEdit => ({
    patch: { tag_ids: tags.map((tag) => tag.id) },
    shows: { tags },
  });
  return (
    <FieldFrame label={label} save={save}>
      <TagPicker
        selectedTags={task.tags}
        onChange={(tags) =>
          void save.save(edit(tags), tags.length === 0 ? edit(task.tags) : undefined)
        }
        disabled={readOnly}
        placeholder={t("taskForm.tagsPlaceholder")}
      />
    </FieldFrame>
  );
};

/** A stored date as the pickers hold it: local, to the minute. */
const toLocalInputValue = (value: string | null) => {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return "";
  const pad = (segment: number) => segment.toString().padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

const DATE_FIELDS = [
  { key: "start", field: "start_date", label: "taskForm.startDateLabel", id: "task-start-date" },
  { key: "due", field: "due_date", label: "taskForm.dueDateLabel", id: "task-due-date" },
] as const;

type DatePair = Record<(typeof DATE_FIELDS)[number]["key"], string>;

/** The start and due dates, as one control: checked and saved as a pair. */
const DatesEditor = ({ task }: { task: TaskRead }) => {
  const { t } = useTranslation(["tasks", "dates", "common"]);
  const { readOnly, askScope } = useTaskPage();
  const save = useTaskFieldSave(task, t("taskForm.sections.schedule"), askScope);
  const saved: DatePair = {
    start: toLocalInputValue(task.start_date),
    due: toLocalInputValue(task.due_date),
  };
  const inverted = (pair: DatePair) => dateRangeBounds(pair.start, pair.due).isInverted;
  // Only the dates that moved are sent; Undo puts back what was stored.
  const draft = useFieldDraft(
    saved,
    (pair) => {
      const moved = DATE_FIELDS.filter(({ key }) => pair[key] !== saved[key]);
      const at = (local: string) => (local ? new Date(local).toISOString() : null);
      const edit: TaskEdit = { patch: {}, shows: {} };
      const undo: TaskEdit = { patch: {}, shows: {} };
      for (const { key, field } of moved) {
        edit.patch[field] = at(pair[key]);
        edit.shows[field] = at(pair[key]);
        undo.patch[field] = task[field];
        undo.shows[field] = task[field];
      }
      return save.save(edit, moved.some(({ key }) => !pair[key]) ? undo : undefined);
    },
    sameJson,
    (pair) => !inverted(pair)
  );
  const range = dateRangeBounds(draft.value.start, draft.value.due);
  const calendarProps = { start: range.startCalendarProps, due: range.endCalendarProps };
  return (
    <FieldFrame
      label={t("taskForm.sections.schedule")}
      save={save}
      changed={draft.changed}
      keys={draft.keys}
    >
      <div className="grid grid-cols-pair gap-4">
        {DATE_FIELDS.map(({ key, label, id }) => (
          <div key={key} className="space-y-2">
            <Label htmlFor={id} className="font-normal text-muted-foreground text-xs">
              {t(label)}
            </Label>
            <DateTimePicker
              id={id}
              value={draft.value[key]}
              onChange={(next) => draft.edit({ ...draft.value, [key]: next })}
              disabled={readOnly}
              placeholder={t("common:optional")}
              calendarProps={calendarProps[key]}
            />
          </div>
        ))}
      </div>
      {range.isInverted ? (
        <p className="text-destructive text-sm" role="alert">
          {t("dates:invalidRange")}
        </p>
      ) : null}
    </FieldFrame>
  );
};

type Repeat = { rule: RecurrenceRule | "custom" | null; strategy: TaskRead["recurrence_strategy"] };

const TaskRecurrenceEditor = ({ task, label }: EditorProps) => {
  const { readOnly, askScope } = useTaskPage();
  const save = useTaskFieldSave(task, label, askScope);
  const start = task.due_date ?? task.start_date;
  const saved: Repeat = {
    rule: fromStored(task.recurrence, start, task.recurrence_shift),
    strategy: task.recurrence_strategy ?? "fixed",
  };
  const edit = ({ rule, strategy }: Repeat): TaskEdit => ({
    patch: { ...rulePayload(rule), recurrence_strategy: rule ? strategy : "fixed" },
    // The stored rule is the server's to work out from the zone it is sent with.
    shows: rule
      ? { recurrence_strategy: strategy }
      : { recurrence: null, recurrence_strategy: "fixed" },
  });
  // A rule this editor cannot show cannot be sent back, so only a rule it can
  // is offered back after it is removed.
  const draft = useFieldDraft(
    saved,
    (repeat) =>
      save.save(
        edit(repeat),
        repeat.rule === null && saved.rule !== "custom"
          ? {
              ...edit(saved),
              shows: { recurrence: task.recurrence, recurrence_strategy: saved.strategy },
            }
          : undefined
      ),
    sameJson
  );
  return (
    <FieldFrame label={label} hideLabel save={save} changed={draft.changed} keys={draft.keys}>
      <RecurrenceEditor
        kind="task"
        value={draft.value.rule}
        onChange={(rule) => draft.edit({ ...draft.value, rule })}
        strategy={draft.value.strategy}
        onStrategyChange={(strategy) => draft.edit({ ...draft.value, strategy })}
        disabled={readOnly}
        referenceDate={start}
        stored={task.recurrence ? { rule: task.recurrence, shift: task.recurrence_shift } : null}
      />
    </FieldFrame>
  );
};

/** How a value reads on the task until the server says: a person's own
 *  summary while they are still the one named. */
const showing = (property: PropertySummary, value: unknown): PropertySummary => ({
  ...property,
  value: value === normalizePropertyValue(property) ? property.value : value,
});

/** One custom property, saved on its own as its kind says. Only it is sent,
 *  so a change to another property meanwhile still stands. */
const PropertyEditor = ({ task, property }: { task: TaskRead; property: PropertySummary }) => {
  const { t } = useTranslation("properties");
  const { readOnly, initiativeId, askScope } = useTaskPage();
  const save = useTaskFieldSave(task, property.name, askScope);
  const saved = normalizePropertyValue(property);
  const edit = (value: unknown): TaskEdit => ({
    properties: { values: [{ property_id: property.property_id, value }] },
    shows: {
      properties: task.properties.map((p) =>
        p.property_id === property.property_id ? showing(p, value) : p
      ),
    },
  });
  const draft = useFieldDraft(
    saved,
    (value) =>
      save.save(
        edit(value),
        isEmptyPropertyValue(value) && !isEmptyPropertyValue(saved) ? edit(saved) : undefined
      ),
    sameJson
  );
  // The property stays until it is gone, so a failed removal says so here.
  const remove = () => {
    draft.restore();
    void save.save(
      { properties: { values: [], removed: [property.property_id] }, shows: {} },
      { ...edit(saved), shows: { properties: task.properties } }
    );
  };
  return (
    <FieldFrame
      label={property.name}
      save={save}
      changed={draft.changed}
      keys={draft.keys}
      action={
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="text-muted-foreground"
          onClick={remove}
          disabled={readOnly}
          aria-label={t("remove")}
        >
          <X className="h-4 w-4" />
        </Button>
      }
    >
      <PropertyInput
        definition={property}
        value={draft.value}
        onChange={draft.edit}
        disabled={readOnly}
        initiativeId={initiativeId}
        canOpen={{ tool: Tool.project, id: task.project_id }}
        selectedUser={userReferenceValue(property)}
      />
    </FieldFrame>
  );
};

/** The task's custom properties, each saved on its own, and adding one. */
const PropertiesEditor = ({ task }: { task: TaskRead }) => {
  const { t } = useTranslation("properties");
  const { readOnly, initiativeId, askScope } = useTaskPage();
  const label = t("title");
  const save = useTaskFieldSave(task, label, askScope);
  const add = (definition: PropertyDefinitionRead) => {
    if (task.properties.some((p) => p.property_id === definition.id)) return;
    void save.save({
      properties: { values: [{ property_id: definition.id, value: null }] },
      shows: { properties: [...task.properties, propertyStubFromDefinition(definition)] },
    });
  };
  const sorted = [...task.properties].sort((a, b) => a.name.localeCompare(b.name));
  return (
    <FieldFrame label={label} save={save}>
      {sorted.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("noProperties")}</p>
      ) : (
        sorted.map((property) => (
          <PropertyEditor key={property.property_id} task={task} property={property} />
        ))
      )}
      <AddPropertyButton
        initiativeId={initiativeId ?? 0}
        currentPropertyIds={task.properties.map((p) => p.property_id)}
        onAdd={add}
        disabled={readOnly || !initiativeId}
      />
    </FieldFrame>
  );
};

const Checklist = ({ task }: EditorProps) => {
  const { readOnly } = useTaskPage();
  return <TaskChecklist taskId={task.id} items={task.checklist ?? []} canEdit={!readOnly} />;
};

/** Each field's editor on the task's page, by its kind. */
const FIELD_EDITORS: Partial<Record<FieldKind, ComponentType<EditorProps>>> = {
  title: TitleEditor,
  excerpt: DescriptionEditor,
  people: AssigneesEditor,
  priority: PriorityEditor,
  recurrence: TaskRecurrenceEditor,
  tags: TagsEditor,
  checklist: Checklist,
};

/** Who made the task and when. */
const Byline = ({ task }: { task: TaskRead }) => {
  const { t } = useTranslation("tasks");
  const dateLocale = useDateLocale();
  const createdAt = useMemo(() => new Date(task.created_at), [task.created_at]);
  const relative = useRelativeTime(createdAt);
  const creator = task.creator;
  const anonymized = isAnonymizedUser(creator);
  // A creator who has since left the community is named by id.
  const name =
    creator || task.created_by != null
      ? getUserDisplayName(creator ?? { id: task.created_by })
      : null;
  const avatarSrc = creator && !anonymized ? getAvatarSrc(creator) : undefined;
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="flex w-fit items-center gap-2 text-muted-foreground text-xs">
            {name ? (
              <Avatar className="h-5 w-5 border text-3xs">
                {avatarSrc ? <AvatarImage src={avatarSrc} alt={name} /> : null}
                <AvatarFallback userId={anonymized ? null : (creator?.id ?? null)}>
                  {getInitialsForUser(creator)}
                </AvatarFallback>
              </Avatar>
            ) : null}
            <span>
              {name
                ? t("edit.createdBy", { name, time: relative })
                : t("edit.createdAt", { time: relative })}
            </span>
          </div>
        </TooltipTrigger>
        <TooltipContent>
          {format(createdAt, dateTimePattern("PP", { seconds: true }), { locale: dateLocale })}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};

const Notice = () => {
  const { readOnlyMessage } = useTaskPage();
  return readOnlyMessage ? (
    <p className="rounded-md border border-border bg-muted/50 px-3 py-2 text-muted-foreground text-sm">
      {readOnlyMessage}
    </p>
  ) : null;
};

const Actions = () => <>{useTaskPage().actions}</>;

/** What the task is waiting on. A task is addressed inside its project, so
 *  that is the tool a link refreshes. */
const Relations = ({ task }: { task: TaskRead }) => {
  const { readOnly } = useTaskPage();
  return (
    <ToolRelationsPanel
      tool={Tool.project}
      entity={{ id: task.project_id, initiative_id: task.project?.initiative_id ?? null }}
      target={{ type: SearchEntityType.task, id: task.id }}
      canEdit={!readOnly}
      entityTitle={task.title}
      defaultLayout="rows"
    />
  );
};

const Case = ({ task }: { task: TaskRead }) => (
  <CasePanel taskId={task.id} canEdit={!useTaskPage().readOnly} />
);

const Comments = ({ task }: { task: TaskRead }) => {
  const { t } = useTranslation("tasks");
  const { initiativeId } = useTaskPage();
  const params = { task_id: task.id };
  const query = useComments(params);
  const cache = useCommentsCache(params);
  return (
    <>
      {query.isError ? <p className="text-destructive text-sm">{t("edit.commentsError")}</p> : null}
      <CommentSection
        entityType="task"
        entityId={task.id}
        comments={query.data ?? []}
        isLoading={query.isLoading}
        hasOlder={query.hasNextPage}
        isLoadingOlder={query.isFetchingNextPage}
        onLoadOlder={() => void query.fetchNextPage()}
        onCommentCreated={cache.putComment}
        onCommentDeleted={cache.removeComment}
        onCommentUpdated={cache.putComment}
        initiativeId={initiativeId ?? 0}
      />
    </>
  );
};

/** The parts a task's page is drawn from. */
const TASK_PAGE_PARTS: Parts<TaskRead> = {
  ...LAYOUT_PARTS,
  field: (node, task, view) => {
    const field = view.fields.get(String(node.props?.field));
    const Editor = field ? FIELD_EDITORS[field.kind] : undefined;
    if (!field || !Editor || (field.hideable && view.isHidden(field.id))) return null;
    return <Editor task={task} label={view.env.t(field.label)} />;
  },
  status: (_node, task) => <StatusEditor task={task} />,
  dates: (_node, task) => <DatesEditor task={task} />,
  properties: (_node, task) => <PropertiesEditor task={task} />,
  byline: (_node, task) => <Byline task={task} />,
  notice: () => <Notice />,
  actions: () => <Actions />,
  relations: (_node, task) => <Relations task={task} />,
  case: (_node, task) => <Case task={task} />,
  comments: (_node, task) => <Comments task={task} />,
};

// The page's labels are the fields' own; no field is hidden on it yet.
const PAGE_FIELDS = taskFields([]);

/** A task's page, drawn from its item layout. */
export const TaskPageView = ({ task, page }: { task: TaskRead; page: TaskPageContext }) => {
  const communityId = useActiveCommunityId();
  const gp = useCommunityPath();
  const taskHref = useCallback(
    (taskId: number) => gp(taskRoute(page.initiativeId, task.project_id, taskId)),
    [gp, page.initiativeId, task.project_id]
  );
  const env = useProjectViewEnv(taskHref);
  const view = useMemo<ViewContext>(
    () => ({ fields: PAGE_FIELDS, variant: "page", isHidden: () => false, env }),
    [env]
  );
  return (
    // Another task's page starts afresh, with none of this one's drafts.
    <PageContext.Provider key={`${communityId}:${task.id}`} value={page}>
      {renderNode(TASK_PAGE, task, view, TASK_PAGE_PARTS)}
    </PageContext.Provider>
  );
};
