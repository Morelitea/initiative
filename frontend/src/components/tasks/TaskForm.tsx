import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type {
  PropertyDefinitionRead,
  PropertySummary,
  PropertyValueInput,
  TagSummary,
  TaskListReadRecurrenceStrategy,
  TaskPriority,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { MentionComposer } from "@/components/markdown/MentionComposer";
import { type MemberLike, MemberMultiSelect } from "@/components/members/MemberSearchSelect";
import { AddPropertyButton } from "@/components/properties/AddPropertyButton";
import { PropertyFields, propertyStubFromDefinition } from "@/components/properties/PropertyFields";
import { RecurrenceEditor } from "@/components/recurrence/RecurrenceEditor";
import { TagPicker } from "@/components/tags";
import { TaskDescription } from "@/components/tasks/TaskDescription";
import { TaskPriorityOption } from "@/components/tasks/TaskPriorityOption";
import { statusTriggerStyle, TaskStatusOption } from "@/components/tasks/TaskStatusOption";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
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
import { usePastedImages } from "@/hooks/usePastedImages";
import { dateRangeBounds } from "@/lib/dateRange";
import type { RecurrenceRule } from "@/lib/recurrence";
import { PRIORITY_ORDER } from "@/lib/sorting";
import { cn } from "@/lib/utils";

/** A description's preview reads the way the saved one will. */
const renderDescription = (draft: string) => <TaskDescription content={draft} />;

/** The full editable state of a task form, owned by the parent so it can
 *  build a create/update payload, compare against a snapshot for dirty
 *  tracking, and reset on success. The fields change it only through
 *  ``onChange``. */
export interface TaskFormValue {
  title: string;
  description: string;
  statusId: number | null;
  priority: TaskPriority;
  assigneeIds: number[];
  startDate: string;
  dueDate: string;
  /** `"custom"` is a stored rule the form can't show, kept until replaced. */
  recurrence: RecurrenceRule | "custom" | null;
  recurrenceStrategy: TaskListReadRecurrenceStrategy;
  tags: TagSummary[];
  /** Attached property rows — real server rows or locally-added stubs. */
  properties: PropertySummary[];
  /** Current value keyed by ``property_id``. */
  propertyValues: Record<number, unknown>;
}

/** Order-stable projection of a form value, for equality / dirty comparison. */
export const serializeTaskFormValue = (value: TaskFormValue): string =>
  JSON.stringify({
    title: value.title,
    description: value.description,
    statusId: value.statusId,
    priority: value.priority,
    assigneeIds: [...value.assigneeIds].sort((a, b) => a - b),
    startDate: value.startDate,
    dueDate: value.dueDate,
    recurrence: value.recurrence,
    recurrenceStrategy: value.recurrenceStrategy,
    tags: value.tags.map((tag) => tag.id).sort((a, b) => a - b),
    properties: value.properties.map((p) => p.property_id).sort((a, b) => a - b),
    propertyValues: Object.keys(value.propertyValues)
      .map(Number)
      .sort((a, b) => a - b)
      .map((id) => [id, value.propertyValues[id] ?? null]),
  });

/** The form's properties as the replace-all body of a property write. */
export const taskFormPropertyValues = (value: TaskFormValue): PropertyValueInput[] =>
  value.properties.map((property) => ({
    property_id: property.property_id,
    value: value.propertyValues[property.property_id] ?? null,
  }));

/** A blank value for a fresh task form. */
export const emptyTaskFormValue = (overrides: Partial<TaskFormValue> = {}): TaskFormValue => ({
  title: "",
  description: "",
  statusId: null,
  priority: "medium",
  assigneeIds: [],
  startDate: "",
  dueDate: "",
  recurrence: null,
  recurrenceStrategy: "fixed",
  tags: [],
  properties: [],
  propertyValues: {},
  ...overrides,
});

/**
 * The create dialog's sections, in render order, and the ``TaskFormValue``
 * keys each one owns: the dialog shows the first and collapses the rest. (The
 * task page lays the same fields out in Tavern's ``task.page`` template.)
 *
 * ``taskForm.sections`` in ``TaskForm.test.tsx`` asserts these keys cover
 * ``TaskFormValue`` exactly, so adding a field to the value without giving
 * it a section fails CI.
 */
export const TASK_FORM_SECTIONS = [
  { id: "details", keys: ["title", "description"] },
  { id: "tracking", keys: ["statusId", "priority"] },
  { id: "schedule", keys: ["startDate", "dueDate", "recurrence", "recurrenceStrategy"] },
  { id: "people", keys: ["assigneeIds", "tags"] },
  { id: "properties", keys: ["properties", "propertyValues"] },
] as const satisfies readonly {
  id: string;
  keys: readonly (keyof TaskFormValue)[];
}[];

/** What every field of the task form takes. */
export interface TaskFieldProps {
  value: TaskFormValue;
  onChange: (patch: Partial<TaskFormValue>) => void;
  disabled?: boolean;
  /** For the field's outermost element, as a template places it. */
  className?: string;
}

/** For a field whose typed inputs may sit outside their form. */
interface TaskFormInputProps {
  /** The form its typed inputs submit with, when the field sits outside that
   *  form (`<input form>`): Enter in one submits it, and the browser's own
   *  checks on the value hold it back. */
  form?: string;
}

export const TaskTitleField = ({
  value,
  onChange,
  disabled,
  className,
  form,
  autoFocus,
  inputClassName,
}: TaskFieldProps &
  TaskFormInputProps & {
    autoFocus?: boolean;
    inputClassName?: string;
  }) => {
  const { t } = useTranslation("tasks");
  return (
    <div className={cn("space-y-2", className)}>
      <Label htmlFor="task-title">{t("taskForm.titleLabel")}</Label>
      <Input
        id="task-title"
        form={form}
        value={value.title}
        onChange={(event) => onChange({ title: event.target.value })}
        placeholder={t("taskForm.titlePlaceholder")}
        required
        disabled={disabled}
        autoFocus={autoFocus}
        className={inputClassName}
      />
    </div>
  );
};

export const TaskStatusField = ({
  value,
  onChange,
  disabled,
  className,
  statuses,
}: TaskFieldProps & { statuses: TaskStatusRead[] }) => {
  const { t } = useTranslation("tasks");
  const current = value.statusId
    ? (statuses.find((status) => status.id === value.statusId) ?? null)
    : null;
  return (
    <div className={cn("space-y-2", className)}>
      <Label>{t("taskForm.statusLabel")}</Label>
      <Select
        value={value.statusId ? String(value.statusId) : undefined}
        onValueChange={(selected) => {
          const parsed = Number(selected);
          if (Number.isFinite(parsed)) {
            onChange({ statusId: parsed });
          }
        }}
        disabled={disabled || statuses.length === 0}
      >
        <SelectTrigger
          className="border-2"
          style={current ? statusTriggerStyle(current) : undefined}
          disabled={disabled || statuses.length === 0}
        >
          {current ? (
            <TaskStatusOption status={current} />
          ) : (
            <SelectValue placeholder={t("taskForm.selectStatus")} />
          )}
        </SelectTrigger>
        <SelectContent>
          {statuses.map((status) => (
            <SelectItem key={status.id} value={String(status.id)}>
              <TaskStatusOption status={status} />
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
};

export const TaskPriorityField = ({ value, onChange, disabled, className }: TaskFieldProps) => {
  const { t } = useTranslation("tasks");
  return (
    <div className={cn("space-y-2", className)}>
      <Label>{t("taskForm.priorityLabel")}</Label>
      <Select
        value={value.priority}
        onValueChange={(selected) => onChange({ priority: selected as TaskPriority })}
        disabled={disabled}
      >
        <SelectTrigger disabled={disabled}>
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
    </div>
  );
};

/** The start and due dates, and a warning when they are the wrong way round. */
export const TaskDatesField = ({ value, onChange, disabled, className }: TaskFieldProps) => {
  const { t } = useTranslation(["tasks", "dates", "common"]);
  const range = dateRangeBounds(value.startDate, value.dueDate);
  return (
    <div className={cn("space-y-2", className)}>
      <div className="grid grid-cols-pair gap-4">
        <div className="space-y-2">
          <Label htmlFor="task-start-date">{t("taskForm.startDateLabel")}</Label>
          <DateTimePicker
            id="task-start-date"
            value={value.startDate}
            onChange={(next) => onChange({ startDate: next })}
            disabled={disabled}
            placeholder={t("common:optional")}
            calendarProps={range.startCalendarProps}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="task-due-date">{t("taskForm.dueDateLabel")}</Label>
          <DateTimePicker
            id="task-due-date"
            value={value.dueDate}
            onChange={(next) => onChange({ dueDate: next })}
            disabled={disabled}
            placeholder={t("common:optional")}
            calendarProps={range.endCalendarProps}
          />
        </div>
      </div>
      {range.isInverted ? (
        <p className="text-destructive text-sm" role="alert">
          {t("dates:invalidRange")}
        </p>
      ) : null}
    </div>
  );
};

export const TaskRecurrenceField = ({
  value,
  onChange,
  disabled,
  className,
  form,
  referenceDate,
  stored,
}: TaskFieldProps &
  TaskFormInputProps & {
    /** Reference date for the "occurs on" preview. */
    referenceDate?: string | null;
    /** The stored repeat and its shift, previewed while it is kept as custom. */
    stored?: { rule: string; shift: number } | null;
  }) => {
  const editor = (
    <RecurrenceEditor
      kind="task"
      form={form}
      value={value.recurrence}
      onChange={(recurrence) => onChange({ recurrence })}
      strategy={value.recurrenceStrategy}
      onStrategyChange={(recurrenceStrategy) => onChange({ recurrenceStrategy })}
      disabled={disabled}
      referenceDate={referenceDate ?? value.dueDate ?? value.startDate}
      stored={stored}
    />
  );
  // The editor draws its own outermost element, so classes need one around it.
  return className ? <div className={className}>{editor}</div> : editor;
};

export const TaskAssigneesField = ({
  value,
  onChange,
  disabled,
  className,
  projectId,
  currentUserId,
  selectedAssignees,
}: TaskFieldProps & {
  projectId: number | null;
  currentUserId?: number;
  /** Pre-known assignee users so the picker renders names without a search. */
  selectedAssignees?: MemberLike[];
}) => {
  const { t } = useTranslation("tasks");
  return (
    <div className={cn("space-y-2", className)}>
      <Label>{t("taskForm.assigneesLabel")}</Label>
      <MemberMultiSelect
        scope={{ type: "canOpen", tool: Tool.project, id: projectId ?? null }}
        selectedIds={value.assigneeIds}
        selectedUsers={selectedAssignees}
        onChange={(ids) => onChange({ assigneeIds: ids })}
        disabled={disabled}
        emptyMessage={t("taskForm.assigneesEmptyMessage")}
        currentUserId={currentUserId}
      />
    </div>
  );
};

export const TaskTagsField = ({ value, onChange, disabled, className }: TaskFieldProps) => {
  const { t } = useTranslation("tasks");
  return (
    <div className={cn("space-y-2", className)}>
      <Label>{t("taskForm.tagsLabel")}</Label>
      <TagPicker
        selectedTags={value.tags}
        onChange={(tags) => onChange({ tags })}
        disabled={disabled}
        placeholder={t("taskForm.tagsPlaceholder")}
      />
    </div>
  );
};

/** The task's custom properties: adding, editing and removing them. */
export const TaskPropertiesField = ({
  value,
  onChange,
  disabled,
  className,
  form,
  projectId,
  initiativeId,
}: TaskFieldProps &
  TaskFormInputProps & { projectId: number | null; initiativeId: number | null }) => {
  const handleAdd = (definition: PropertyDefinitionRead) => {
    if (value.properties.some((p) => p.property_id === definition.id)) return;
    onChange({
      properties: [...value.properties, propertyStubFromDefinition(definition)],
      propertyValues: { ...value.propertyValues, [definition.id]: null },
    });
  };
  const handleRemove = (propertyId: number) => {
    const nextValues = { ...value.propertyValues };
    delete nextValues[propertyId];
    onChange({
      properties: value.properties.filter((p) => p.property_id !== propertyId),
      propertyValues: nextValues,
    });
  };
  return (
    <div className={cn("space-y-2", className)}>
      <PropertyFields
        properties={value.properties}
        values={value.propertyValues}
        onChange={(propertyId, next) =>
          onChange({ propertyValues: { ...value.propertyValues, [propertyId]: next } })
        }
        onRemove={handleRemove}
        disabled={disabled}
        initiativeId={initiativeId}
        canOpen={{ tool: Tool.project, id: projectId }}
        form={form}
      />
      <AddPropertyButton
        initiativeId={initiativeId ?? 0}
        currentPropertyIds={value.properties.map((property) => property.property_id)}
        onAdd={handleAdd}
        disabled={disabled || !initiativeId}
      />
    </div>
  );
};

export interface TaskFormProps {
  value: TaskFormValue;
  onChange: (value: TaskFormValue) => void;

  statuses: TaskStatusRead[];
  projectId: number | null;
  initiativeId: number | null;
  currentUserId?: number;
  /** Pre-known assignee users so the picker renders names without a search. */
  selectedAssignees?: MemberLike[];
  disabled?: boolean;
  autoFocusTitle?: boolean;
}

/**
 * The create dialog's field set: the title and description, with everything
 * else in a collapsible section. The parent owns the ``value`` (for submit,
 * dirty tracking and reset) and the ``<form>`` around it.
 */
export const TaskForm = ({
  value,
  onChange,
  statuses,
  projectId,
  initiativeId,
  currentUserId,
  selectedAssignees,
  disabled = false,
  autoFocusTitle = false,
}: TaskFormProps) => {
  const { t } = useTranslation(["tasks", "properties"]);
  const uploadImage = usePastedImages();
  const field = {
    value,
    onChange: (patch: Partial<TaskFormValue>) => onChange({ ...value, ...patch }),
    disabled,
  };

  const sectionContent: Record<(typeof TASK_FORM_SECTIONS)[number]["id"], ReactNode> = {
    details: (
      <>
        <TaskTitleField {...field} autoFocus={autoFocusTitle} />
        <div className="space-y-2">
          <Label htmlFor="task-description">{t("taskForm.descriptionLabel")}</Label>
          <MentionComposer
            id="task-description"
            rows={3}
            compact
            value={value.description}
            onChange={(description) => field.onChange({ description })}
            initiativeId={initiativeId ?? 0}
            renderPreview={renderDescription}
            onUploadImage={uploadImage}
            placeholder={t("taskForm.descriptionPlaceholder")}
            disabled={disabled}
          />
        </div>
      </>
    ),
    tracking: (
      <div className="grid grid-cols-pair gap-4">
        <TaskStatusField {...field} statuses={statuses} />
        <TaskPriorityField {...field} />
      </div>
    ),
    schedule: (
      <>
        <TaskDatesField {...field} />
        <TaskRecurrenceField {...field} />
      </>
    ),
    people: (
      <div className="grid grid-cols-pair gap-4">
        <TaskAssigneesField
          {...field}
          projectId={projectId}
          currentUserId={currentUserId}
          selectedAssignees={selectedAssignees}
        />
        <TaskTagsField {...field} />
      </div>
    ),
    properties: (
      <TaskPropertiesField {...field} projectId={projectId} initiativeId={initiativeId} />
    ),
  };

  // The leading section needs no heading: a title and a description under the
  // dialog's own heading announce themselves.
  const sectionHeading: Record<(typeof TASK_FORM_SECTIONS)[number]["id"], string | null> = {
    details: null,
    tracking: t("taskForm.sections.tracking"),
    schedule: t("taskForm.sections.schedule"),
    people: t("taskForm.sections.people"),
    properties: t("properties:title"),
  };

  const renderSection = ({ id }: (typeof TASK_FORM_SECTIONS)[number]) => (
    <section key={id} className="space-y-4">
      {sectionHeading[id] ? (
        <h2 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
          {sectionHeading[id]}
        </h2>
      ) : null}
      {sectionContent[id]}
    </section>
  );

  const [leadSection, ...detailSections] = TASK_FORM_SECTIONS;

  return (
    <div className="space-y-4">
      {renderSection(leadSection)}
      <Accordion type="single" collapsible>
        <AccordionItem value="advanced">
          <AccordionTrigger>{t("taskForm.advancedDetails")}</AccordionTrigger>
          <AccordionContent className="space-y-6">
            {detailSections.map(renderSection)}
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  );
};
