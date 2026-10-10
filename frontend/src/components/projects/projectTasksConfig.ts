import type { TFunction } from "i18next";
import { Calendar, Kanban, type LucideIcon, Table } from "lucide-react";

import type { TaskPriority, ViewLayoutType } from "@/api/generated/initiativeAPI.schemas";

export type DueFilterOption = "all" | "today" | "7_days" | "30_days" | "overdue";

export type PriorityBadgeVariant = "default" | "secondary" | "warning" | "destructive";

export const priorityVariant: Record<TaskPriority, PriorityBadgeVariant> = {
  low: "secondary",
  medium: "default",
  high: "warning",
  urgent: "destructive",
};

/** The dot beside a priority in a dropdown, in the colour of its badge.
 *  `low`'s badge is a near-background surface, so its dot takes the muted
 *  text colour to stay visible. */
export const priorityDotClass: Record<TaskPriority, string> = {
  low: "bg-muted-foreground",
  medium: "bg-primary",
  high: "bg-warning",
  urgent: "bg-destructive",
};

/** Each view layout's icon, and its name in `projects`. */
export const viewLayouts: Record<ViewLayoutType, { icon: LucideIcon; labelKey: string }> = {
  table: { icon: Table, labelKey: "tasks.viewTable" },
  board: { icon: Kanban, labelKey: "tasks.viewBoard" },
  calendar: { icon: Calendar, labelKey: "tasks.viewCalendar" },
};

/** The views Initiative ships for a project, by slug: the name each is shipped
 *  with and its name in `projects` (mirrors `SHIPPED` in the backend). */
const SHIPPED_NAMES: Partial<Record<string, { name: string; labelKey: string }>> = {
  table: { name: "Table", labelKey: viewLayouts.table.labelKey },
  board: { name: "Board", labelKey: viewLayouts.board.labelKey },
  calendar: { name: "Calendar", labelKey: viewLayouts.calendar.labelKey },
  incomplete: { name: "Incomplete", labelKey: "views.shipped.incomplete" },
  unassigned: { name: "Unassigned", labelKey: "views.shipped.unassigned" },
  mine: { name: "Mine", labelKey: "views.shipped.mine" },
};

/** A view's name to show. A shipped view still carrying its shipped name is
 *  shown in the reader's language; once renamed, it is shown as named. What is
 *  saved is always the name as stored. */
export const viewName = (
  view: { slug: string; name: string },
  t: TFunction<readonly ["projects", "common"]>
): string => {
  const shipped = SHIPPED_NAMES[view.slug];
  return shipped?.name === view.name ? t(shipped.labelKey as never) : view.name;
};
