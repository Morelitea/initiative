/**
 * Reading a project listing.
 *
 * A project listing is the project's export envelope (backend
 * `ProjectExportEnvelope`), and so is its example. The API types both as an
 * open object, so this names the parts a listing page shows and checks the
 * shape it was given before anything reads it.
 *
 * A listing stores dates as offsets: its earliest one sits on a fixed day, and
 * installing moves that day to the start date the installer picks. So a date
 * here means nothing on its own and is shown as a distance from the earliest.
 */

import type {
  PropertyOption,
  PropertyType,
  TaskPriority,
  TaskStatusCategory,
} from "@/api/generated/initiativeAPI.schemas";

export interface ProjectListingStatus {
  name: string;
  category: TaskStatusCategory;
  position: number;
  color?: string | null;
  icon?: string | null;
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
  options?: PropertyOption[] | null;
}

export interface ProjectListingTask {
  title: string;
  priority: TaskPriority;
  start_date?: string | null;
  due_date?: string | null;
  status_name: string;
  checklist: { text: string; done: boolean }[];
  properties: ProjectListingPropertyValue[];
}

export interface ProjectListingEnvelope {
  project: { name: string; start_date?: string | null; end_date?: string | null };
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

/** Every date the envelope carries: the project's span and each task's. */
const datesOf = (envelope: ProjectListingEnvelope): string[] =>
  [
    envelope.project.start_date,
    envelope.project.end_date,
    ...envelope.tasks.flatMap((task) => [task.start_date, task.due_date]),
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

/**
 * How far each date sits from the envelope's earliest, in whole days:
 * `0` for the earliest itself. A function of the envelope, because the
 * earliest date is the anchor every other one is read against.
 */
export const dayOffsetsFrom = (
  envelope: ProjectListingEnvelope
): ((date: string | null | undefined) => number | null) => {
  const days = datesOf(envelope).map(dayNumber);
  const earliest = days.length ? Math.min(...days) : 0;
  return (date) => (date ? dayNumber(date) - earliest : null);
};
