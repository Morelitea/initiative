/**
 * What the initiative's calendar narrows its grid by: what its tasks are, and
 * the properties its events and tasks carry. The page keeps a person's own on
 * the device; a preset on the calendar's layout holds the same shape.
 */

import type { TaskPriority, TaskStatusCategory } from "@/api/generated/initiativeAPI.schemas";
import type { PropertyFilterCondition } from "@/components/properties/PropertyFilter";

export type CalendarFilters = {
  status_categories: TaskStatusCategory[];
  priorities: TaskPriority[];
  properties: PropertyFilterCondition[];
};

export const EMPTY_CALENDAR_FILTERS: CalendarFilters = {
  status_categories: [],
  priorities: [],
  properties: [],
};

const strings = <T extends string>(raw: unknown): T[] =>
  Array.isArray(raw) ? raw.filter((value): value is T => typeof value === "string") : [];

/** Coerce kept filters (every key optional) into the whole shape. */
export const calendarFiltersFromStored = (
  raw: Partial<Record<keyof CalendarFilters, unknown>> | null | undefined
): CalendarFilters => ({
  status_categories: strings<TaskStatusCategory>(raw?.status_categories),
  priorities: strings<TaskPriority>(raw?.priorities),
  properties: Array.isArray(raw?.properties)
    ? (raw.properties as PropertyFilterCondition[]).filter(
        (entry) => typeof entry?.property_id === "number"
      )
    : [],
});
