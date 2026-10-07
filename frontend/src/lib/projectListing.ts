/**
 * Reading a project listing.
 *
 * A project listing is the project's export envelope (backend
 * `ProjectExportEnvelope`), and so is its example. The API types both as an
 * open object, so this names the parts a listing page shows and checks the
 * shape it was given before anything reads it.
 *
 * A listing stores dates as offsets: its earliest one sits on a fixed day, and
 * installing moves that day to the start date the installer picks. The board
 * a listing previews on moves them to today, as installing today would.
 */

import type {
  PropertyDefinitionRead,
  PropertyOption,
  PropertySummary,
  PropertyType,
  TaskListRead,
  TaskListReadRecurrenceStrategy,
  TaskPriority,
  TaskStatusCategory,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { defaultsForCategory } from "@/lib/taskStatusDefaults";

export interface ProjectListingStatus {
  name: string;
  category: TaskStatusCategory;
  position: number;
  color?: string | null;
  icon?: string | null;
  is_default?: boolean;
}

export interface ProjectListingPropertyValue {
  property_name: string;
  property_type: PropertyType;
  value_text?: string | null;
  value_number?: number | null;
  value_boolean?: boolean | null;
  value_json?: unknown;
}

export interface ProjectListingPropertyDefinition {
  name: string;
  type: PropertyType;
  position: number;
  color?: string | null;
  options?: PropertyOption[] | null;
}

export interface ProjectListingTask {
  title: string;
  description?: string | null;
  priority: TaskPriority;
  start_date?: string | null;
  due_date?: string | null;
  completed_at?: string | null;
  recurrence?: string | Record<string, unknown> | null;
  recurrence_strategy?: TaskListReadRecurrenceStrategy;
  recurrence_shift?: number;
  recurrence_occurrence_count?: number;
  position?: number;
  status_name: string;
  checklist: { text: string; done: boolean }[];
  properties: ProjectListingPropertyValue[];
}

export interface ProjectListingEnvelope {
  project: {
    name: string;
    start_date?: string | null;
    end_date?: string | null;
    properties?: ProjectListingPropertyValue[];
  };
  task_statuses: ProjectListingStatus[];
  property_definitions: ProjectListingPropertyDefinition[];
  tasks: ProjectListingTask[];
}

/** The envelope, or null when what was given is not one. */
export const readProjectEnvelope = (value: unknown): ProjectListingEnvelope | null => {
  if (!value || typeof value !== "object") return null;
  const envelope = value as Partial<ProjectListingEnvelope>;
  return envelope.project &&
    Array.isArray(envelope.task_statuses) &&
    Array.isArray(envelope.property_definitions) &&
    Array.isArray(envelope.tasks)
    ? (envelope as ProjectListingEnvelope)
    : null;
};

const DATE_PROPERTY_TYPES: ReadonlySet<string> = new Set(["date", "datetime"]);

/** Every date the envelope plans with, which are the ones installing moves:
 *  the project's span, each task's dates, and every date-typed property value. */
const datesOf = (envelope: ProjectListingEnvelope): string[] =>
  [
    envelope.project.start_date,
    envelope.project.end_date,
    ...envelope.tasks.flatMap((task) => [task.start_date, task.due_date, task.completed_at]),
    ...[envelope.project.properties ?? [], ...envelope.tasks.map((task) => task.properties)]
      .flat()
      .filter((value) => DATE_PROPERTY_TYPES.has(value.property_type))
      .map((value) => value.value_text),
  ].filter((date): date is string => Boolean(date));

/** Whether installing this envelope places anything on a calendar, and so
 *  whether a start date is worth asking for. */
export const projectEnvelopeHasDates = (envelope: ProjectListingEnvelope | null): boolean =>
  envelope ? datesOf(envelope).length > 0 : false;

const MS_PER_DAY = 86_400_000;

/** The calendar day a stored date names, as a day count. Read from the date
 *  part alone, so a task's time of day and the viewer's zone do not move it. */
const dayNumber = (date: string): number => {
  const [year, month, day] = date.slice(0, 10).split("-").map(Number);
  return Date.UTC(year, month - 1, day) / MS_PER_DAY;
};

/** `value` moved by `days`: a date stays a date, a timestamp keeps its time. */
const shifted = (value: string | null | undefined, days: number): string | null => {
  if (!value) return null;
  if (value.length === 10) {
    return new Date((dayNumber(value) + days) * MS_PER_DAY).toISOString().slice(0, 10);
  }
  return new Date(new Date(value).getTime() + days * MS_PER_DAY).toISOString();
};

/** A description as a card's excerpt: its words, without the markdown's
 *  emphasis and heading marks. */
const excerptOf = (description: string): string =>
  description
    .replace(/[*_`#>]/g, "")
    .split(/\s+/)
    .join(" ")
    .trim();

export interface ProjectListingBoard {
  taskStatuses: TaskStatusRead[];
  groupedTasks: Record<number, TaskListRead[]>;
  propertyDefinitions: PropertyDefinitionRead[];
}

/**
 * What the project board draws, built from the envelope alone.
 *
 * The ids follow the envelope's own order, starting at 1. Nothing here exists
 * in a community, so nothing carries a community, an initiative or a person.
 * The dates move so the earliest falls on `today` (`YYYY-MM-DD`), which is
 * where installing today puts them.
 */
export const projectListingBoard = (
  envelope: ProjectListingEnvelope,
  today: string
): ProjectListingBoard => {
  const days = datesOf(envelope).map(dayNumber);
  const shift = days.length ? dayNumber(today) - Math.min(...days) : 0;

  const taskStatuses: TaskStatusRead[] = [...envelope.task_statuses]
    .sort((a, b) => a.position - b.position)
    .map((status, index) => {
      // A status without its own look takes its category's, as installing does.
      const look = defaultsForCategory(status.category);
      return {
        id: index + 1,
        project_id: 0,
        name: status.name,
        category: status.category,
        position: status.position,
        is_default: status.is_default ?? false,
        color: status.color ?? look.color,
        icon: status.icon ?? look.icon,
      };
    });

  const propertyDefinitions: PropertyDefinitionRead[] = envelope.property_definitions.map(
    (definition, index) => ({
      id: index + 1,
      initiative_id: 0,
      name: definition.name,
      type: definition.type,
      position: definition.position,
      color: definition.color ?? null,
      options: definition.options ?? null,
      created_at: "",
      updated_at: "",
    })
  );

  const summaryOf = (value: ProjectListingPropertyValue): PropertySummary[] => {
    const definition = propertyDefinitions.find((d) => d.name === value.property_name);
    if (!definition) return [];
    return [
      {
        property_id: definition.id,
        name: definition.name,
        type: definition.type,
        options: definition.options,
        value: DATE_PROPERTY_TYPES.has(value.property_type)
          ? shifted(value.value_text, shift)
          : (value.value_text ?? value.value_number ?? value.value_boolean ?? value.value_json),
      },
    ];
  };

  const groupedTasks: Record<number, TaskListRead[]> = {};
  envelope.tasks.forEach((task, index) => {
    const status = taskStatuses.find((s) => s.name === task.status_name);
    if (!status) return;
    groupedTasks[status.id] ??= [];
    groupedTasks[status.id].push({
      id: index + 1,
      project_id: 0,
      project_name: envelope.project.name,
      title: task.title,
      priority: task.priority,
      start_date: shifted(task.start_date, shift),
      due_date: shifted(task.due_date, shift),
      completed_at: shifted(task.completed_at, shift),
      // A repeat published before RRULE keeps a shape the board does not read.
      recurrence: typeof task.recurrence === "string" ? task.recurrence : null,
      recurrence_strategy: task.recurrence_strategy ?? "fixed",
      recurrence_shift: task.recurrence_shift ?? 0,
      recurrence_occurrence_count: task.recurrence_occurrence_count ?? 0,
      recurrence_until: null,
      description_excerpt: task.description ? excerptOf(task.description) : null,
      has_description: Boolean(task.description),
      task_status_id: status.id,
      task_status: status,
      position: task.position ?? index,
      created_at: "",
      updated_at: "",
      archived_at: null,
      created_by: null,
      assignees: [],
      comment_count: 0,
      blocked_by_open_count: 0,
      community_id: null,
      community_name: null,
      initiative_id: null,
      initiative_name: null,
      initiative_color: null,
      checklist_progress: {
        completed: task.checklist.filter((item) => item.done).length,
        total: task.checklist.length,
      },
      // A tag chip opens the community's own tag, and a listing's has none yet.
      tags: [],
      properties: task.properties.flatMap(summaryOf),
    });
  });
  for (const tasks of Object.values(groupedTasks)) tasks.sort((a, b) => a.position - b.position);

  return { taskStatuses, groupedTasks, propertyDefinitions };
};
