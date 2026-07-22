import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type {
  PropertyDefinitionRead,
  PropertySummary,
  TagSummary,
  TaskListReadRecurrenceStrategy,
  TaskPriority,
  TaskRecurrenceOutput,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { type MemberLike, MemberMultiSelect } from "@/components/members/MemberSearchSelect";
import { TaskRecurrenceSelector } from "@/components/projects/TaskRecurrenceSelector";
import { AddPropertyButton } from "@/components/properties/AddPropertyButton";
import { PropertyFields, propertyStubFromDefinition } from "@/components/properties/PropertyFields";
import { TagPicker } from "@/components/tags";
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
import { Textarea } from "@/components/ui/textarea";
import { PRIORITY_ORDER } from "@/lib/sorting";

/** The full editable state of a task form, owned by the parent so it can
 *  build a create/update payload, compare against a snapshot for dirty
 *  tracking, and reset on success. TaskForm mutates it only via ``onChange``. */
export interface TaskFormValue {
  title: string;
  description: string;
  statusId: number | null;
  priority: TaskPriority;
  assigneeIds: number[];
  startDate: string;
  dueDate: string;
  recurrence: TaskRecurrenceOutput | null;
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

  /** Override the plain description textarea (e.g. the editor's markdown/AI block). */
  descriptionSlot?: ReactNode;
  /** Reference date for the recurrence "occurs on" preview. */
  recurrenceReferenceDate?: string | null;

  /** ``dialog`` tucks everything but the title into a collapsible section;
   *  ``page`` renders every field flat. */
  layout?: "dialog" | "page";
  autoFocusTitle?: boolean;
}

/**
 * Shared task field set used by both the create dialog and the edit page. The
 * parent owns the ``value`` (for submit / dirty-tracking / reset); TaskForm
 * owns the interaction logic — including adding, editing, and removing tags and
 * custom properties — and reports every change through a single ``onChange``.
 * It renders no ``<form>``, submit buttons, or surrounding chrome.
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
  descriptionSlot,
  recurrenceReferenceDate,
  layout = "page",
  autoFocusTitle = false,
}: TaskFormProps) => {
  const { t } = useTranslation(["tasks", "properties", "common"]);

  const set = (patch: Partial<TaskFormValue>) => onChange({ ...value, ...patch });

  const currentStatus = value.statusId
    ? (statuses.find((status) => status.id === value.statusId) ?? null)
    : null;
  const currentPropertyIds = value.properties.map((property) => property.property_id);

  const handlePropertyAdd = (definition: PropertyDefinitionRead) => {
    if (value.properties.some((p) => p.property_id === definition.id)) return;
    set({
      properties: [...value.properties, propertyStubFromDefinition(definition)],
      propertyValues: { ...value.propertyValues, [definition.id]: null },
    });
  };

  const handlePropertyChange = (propertyId: number, next: unknown) => {
    set({ propertyValues: { ...value.propertyValues, [propertyId]: next } });
  };

  const handlePropertyRemove = (propertyId: number) => {
    const nextValues = { ...value.propertyValues };
    delete nextValues[propertyId];
    set({
      properties: value.properties.filter((p) => p.property_id !== propertyId),
      propertyValues: nextValues,
    });
  };

  const statusPriority = (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="space-y-2">
        <Label>{t("taskForm.statusLabel")}</Label>
        <Select
          value={value.statusId ? String(value.statusId) : undefined}
          onValueChange={(selected) => {
            const parsed = Number(selected);
            if (Number.isFinite(parsed)) {
              set({ statusId: parsed });
            }
          }}
          disabled={disabled || statuses.length === 0}
        >
          <SelectTrigger
            className="border-2"
            style={currentStatus ? statusTriggerStyle(currentStatus) : undefined}
            disabled={disabled || statuses.length === 0}
          >
            {currentStatus ? (
              <SelectValue asChild>
                <TaskStatusOption status={currentStatus} />
              </SelectValue>
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
      <div className="space-y-2">
        <Label>{t("taskForm.priorityLabel")}</Label>
        <Select
          value={value.priority}
          onValueChange={(selected) => set({ priority: selected as TaskPriority })}
          disabled={disabled}
        >
          <SelectTrigger disabled={disabled}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PRIORITY_ORDER.map((option) => (
              <SelectItem key={option} value={option}>
                {t(`priority.${option}` as never)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );

  const dates = (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="space-y-2">
        <Label htmlFor="task-start-date">{t("taskForm.startDateLabel")}</Label>
        <DateTimePicker
          id="task-start-date"
          value={value.startDate}
          onChange={(next) => set({ startDate: next })}
          disabled={disabled}
          placeholder={t("common:optional")}
          calendarProps={{ hidden: { after: new Date(value.dueDate) } }}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="task-due-date">{t("taskForm.dueDateLabel")}</Label>
        <DateTimePicker
          id="task-due-date"
          value={value.dueDate}
          onChange={(next) => set({ dueDate: next })}
          disabled={disabled}
          placeholder={t("common:optional")}
          calendarProps={{ hidden: { before: new Date(value.startDate) } }}
        />
      </div>
    </div>
  );

  const assigneesTags = (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="space-y-2">
        <Label>{t("taskForm.assigneesLabel")}</Label>
        <MemberMultiSelect
          scope={{ type: "project", projectId: projectId ?? null }}
          selectedIds={value.assigneeIds}
          selectedUsers={selectedAssignees}
          onChange={(ids) => set({ assigneeIds: ids })}
          disabled={disabled}
          emptyMessage={t("taskForm.assigneesEmptyMessage")}
          currentUserId={currentUserId}
        />
      </div>
      <div className="space-y-2">
        <Label>{t("taskForm.tagsLabel")}</Label>
        <TagPicker
          selectedTags={value.tags}
          onChange={(tags) => set({ tags })}
          disabled={disabled}
          placeholder={t("taskForm.tagsPlaceholder")}
        />
      </div>
    </div>
  );

  const recurrenceField = (
    <TaskRecurrenceSelector
      recurrence={value.recurrence}
      onChange={(recurrence) => set({ recurrence })}
      strategy={value.recurrenceStrategy}
      onStrategyChange={(recurrenceStrategy) => set({ recurrenceStrategy })}
      disabled={disabled}
      referenceDate={recurrenceReferenceDate ?? value.dueDate ?? value.startDate}
    />
  );

  const propertiesField = (
    <section className="space-y-2">
      <Label>{t("properties:title")}</Label>
      <PropertyFields
        properties={value.properties}
        values={value.propertyValues}
        onChange={handlePropertyChange}
        onRemove={handlePropertyRemove}
        disabled={disabled}
        initiativeId={initiativeId}
      />
      <AddPropertyButton
        initiativeId={initiativeId ?? 0}
        currentPropertyIds={currentPropertyIds}
        onAdd={handlePropertyAdd}
        disabled={disabled || !initiativeId}
      />
    </section>
  );

  const descriptionField = descriptionSlot ?? (
    <div className="space-y-2">
      <Label htmlFor="task-description">{t("taskForm.descriptionLabel")}</Label>
      <Textarea
        id="task-description"
        rows={3}
        value={value.description}
        onChange={(event) => set({ description: event.target.value })}
        placeholder={t("taskForm.descriptionPlaceholder")}
        disabled={disabled}
      />
    </div>
  );

  const titleField = (
    <div className="space-y-2">
      <Label htmlFor="task-title">{t("taskForm.titleLabel")}</Label>
      <Input
        id="task-title"
        value={value.title}
        onChange={(event) => set({ title: event.target.value })}
        placeholder={t("taskForm.titlePlaceholder")}
        required
        disabled={disabled}
        autoFocus={autoFocusTitle}
      />
    </div>
  );

  const advancedFields = (
    <>
      {descriptionField}
      {statusPriority}
      {dates}
      {assigneesTags}
      {recurrenceField}
      {propertiesField}
    </>
  );

  if (layout === "dialog") {
    return (
      <div className="space-y-4">
        {titleField}
        <Accordion type="single" collapsible>
          <AccordionItem value="advanced">
            <AccordionTrigger>{t("taskForm.advancedDetails")}</AccordionTrigger>
            <AccordionContent className="space-y-4">{advancedFields}</AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {titleField}
      {advancedFields}
    </div>
  );
};
