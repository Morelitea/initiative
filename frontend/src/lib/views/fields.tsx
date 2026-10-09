import { Link } from "@tanstack/react-router";
import type { LucideIcon } from "lucide-react";
import { type ComponentType, memo } from "react";

import type {
  ChecklistProgress,
  PropertySummary,
  TagSummary,
  TaskAssigneeSummary,
  TaskListRead,
  TaskPriority,
} from "@/api/generated/initiativeAPI.schemas";
import { UnreadDot } from "@/components/notifications/UnreadDot";
import { priorityVariant } from "@/components/projects/projectTasksConfig";
import { TaskAssigneeList } from "@/components/projects/TaskAssigneeList";
import { PropertyValueCell } from "@/components/properties/PropertyValueCell";
import { TagBadge } from "@/components/tags";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { Badge } from "@/components/ui/badge";
import { MentionText } from "@/components/user/MentionText";
import { useUnreadTree } from "@/hooks/useUnreadTree";
import { formatDateTime } from "@/lib/formatDate";
import { summarizeStored } from "@/lib/recurrence";
import { truncateText } from "@/lib/text";
import { cn } from "@/lib/utils";
import type { TranslateFn } from "@/types/i18n";

/** What a view draws. Tasks for now; other kinds join as their tools move. */
export type ViewItem = TaskListRead;

/** Where a field is drawn. A table cell and an item page come later, each a
 *  branch in the renderers below. */
export type ViewVariant = "card";

export type FieldKind =
  | "title"
  | "excerpt"
  | "people"
  | "date"
  | "recurrence"
  | "checklist"
  | "priority"
  | "count"
  | "tags"
  | "property";

/** Anything a view can show about an item. */
export type FieldDef = {
  id: string;
  kind: FieldKind;
  source: "builtin" | "property";
  /** Built-in: an i18n key, in `projects` unless it names its namespace.
   *  Property: its own name, untranslated. */
  label: string;
  /** What the field holds for an item; nothing (null, "", []) draws nothing. */
  value: (item: ViewItem) => unknown;
  /** A title cannot be hidden: a card with no title is not a card. */
  hideable: boolean;
  /** A property field's definition id. */
  propertyId?: number;
  /** The sentence the value sits in, as an i18n key ("Due: {{date}}"). */
  phrase?: string;
  icon?: LucideIcon;
  tone?: "warning";
};

/** What renderers share across a view. It changes with the language, the
 *  community and the item links, not with which fields are shown, so a renderer
 *  whose value is unchanged skips redrawing when the Fields menu changes. */
export type ViewEnv = {
  /** Reads `projects`, and `dates` and `relations` by prefix. */
  t: TranslateFn;
  /** A community-relative path, made absolute. */
  communityPath: (path: string) => string;
  taskHref: (taskId: number) => string;
};

export type FieldRendererProps = {
  value: unknown;
  item: ViewItem;
  field: FieldDef;
  variant: ViewVariant;
  env: ViewEnv;
};

/** Whether a value has nothing to show. A count of none is null by then. */
export const isEmptyValue = (value: unknown): boolean =>
  value == null || value === "" || (Array.isArray(value) && value.length === 0);

// Only the title opens the task: the rest of the card is the card, and a real
// link means middle-click and "open in new tab" work.
const TitleField = ({ value, item, env }: FieldRendererProps) => {
  const unread = useUnreadTree().hasSubject(item.community_id, "task", item.id);
  return (
    <Link
      to={env.taskHref(item.id)}
      draggable={false}
      className="wrap-break-word w-full min-w-0 rounded-sm font-medium underline-offset-4 outline-none hover:underline focus-visible:ring-1 focus-visible:ring-ring"
    >
      {value as string}
      {unread ? <UnreadDot className="ml-2 inline-block align-middle" /> : null}
    </Link>
  );
};

// Two lines of words, not a picture that fills the card.
const ExcerptField = ({ value }: FieldRendererProps) => (
  <p className="wrap-break-word line-clamp-2 w-full min-w-0 text-muted-foreground text-sm">
    <MentionText text={value as string} />
  </p>
);

const PeopleField = ({ value }: FieldRendererProps) => (
  <TaskAssigneeList assignees={value as TaskAssigneeSummary[]} className="text-xs" />
);

// `formatDateTime`, as every timestamp in the app: it honours the reader's
// 12/24-hour choice.
const DateField = ({ value, field, env }: FieldRendererProps) => {
  const date = formatDateTime(value as string);
  if (!date) return null;
  return <p>{field.phrase ? env.t(field.phrase, { date }) : date}</p>;
};

const RecurrenceField = ({ value, item, env }: FieldRendererProps) => {
  const summary = summarizeStored(
    value as string,
    item.due_date || item.start_date,
    { strategy: item.recurrence_strategy, shift: item.recurrence_shift },
    env.t
  );
  return summary ? <p>{truncateText(summary, 80)}</p> : null;
};

const ChecklistField = ({ value }: FieldRendererProps) => (
  <TaskChecklistProgress progress={value as ChecklistProgress} className="w-full pt-1" />
);

const PriorityField = ({ value, field, env }: FieldRendererProps) => {
  const priority = value as TaskPriority;
  const text = priority.replace("_", " ");
  return (
    <Badge variant={priorityVariant[priority]}>
      {field.phrase ? env.t(field.phrase, { priority: text }) : text}
    </Badge>
  );
};

const CountField = ({ value, field, env }: FieldRendererProps) => {
  const count = value as number;
  const Icon = field.icon;
  return (
    <Badge
      variant="outline"
      className={cn(
        "inline-flex items-center gap-1 text-xs",
        field.tone === "warning" && "border-warning/40 text-warning"
      )}
      title={field.phrase ? env.t(field.phrase, { count }) : undefined}
    >
      {Icon ? <Icon className="h-3.5 w-3.5" aria-hidden="true" /> : null}
      {count}
    </Badge>
  );
};

const TagsField = ({ value, env }: FieldRendererProps) =>
  (value as TagSummary[]).map((tag) => (
    <TagBadge key={tag.id} tag={tag} size="sm" to={env.communityPath(`/tags/${tag.id}`)} />
  ));

const PropertyField = ({ value }: FieldRendererProps) => (
  <PropertyValueCell summary={value as PropertySummary} variant="chip" />
);

/** One renderer per kind of field, each skipping a redraw its props don't call
 *  for. */
export const FIELD_RENDERERS: Record<FieldKind, ComponentType<FieldRendererProps>> = {
  title: memo(TitleField),
  excerpt: memo(ExcerptField),
  people: memo(PeopleField),
  date: memo(DateField),
  recurrence: memo(RecurrenceField),
  checklist: memo(ChecklistField),
  priority: memo(PriorityField),
  count: memo(CountField),
  tags: memo(TagsField),
  property: memo(PropertyField),
};
