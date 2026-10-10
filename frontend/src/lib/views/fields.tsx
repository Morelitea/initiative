import { Link } from "@tanstack/react-router";
import type { LucideIcon } from "lucide-react";
import { type ComponentType, memo, useMemo } from "react";
import { useTranslation } from "react-i18next";

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
import { TaskBlockersHoverCard } from "@/components/projects/TaskBlockersHoverCard";
import { TaskDescriptionHoverCard } from "@/components/projects/TaskDescriptionHoverCard";
import { PropertyValueCell } from "@/components/properties/PropertyValueCell";
import { TagBadge } from "@/components/tags";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { DateCell } from "@/components/tasks/TaskDateCell";
import { Badge } from "@/components/ui/badge";
import { MentionText } from "@/components/user/MentionText";
import { useUnreadTree } from "@/hooks/useUnreadTree";
import { useCommunityPath } from "@/lib/communityUrl";
import { formatDateTime } from "@/lib/formatDate";
import { summarizeStored } from "@/lib/recurrence";
import { truncateText } from "@/lib/text";
import { cn } from "@/lib/utils";
import type { TranslateFn } from "@/types/i18n";

import { PluginField, type PluginFieldDecl } from "./plugins";

/** What a view draws. Tasks for now; other kinds join as their tools move. */
export type ViewItem = TaskListRead;

/** Where a field is drawn. On an item's page it is its editor, which the
 *  item's page parts draw (`taskPage.tsx`). */
export type ViewVariant = "card" | "cell" | "page";

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
  | "property"
  | "plugin";

/** A property's field, by its definition id: what a view stores, so renaming
 *  the property keeps every view that shows it. */
export const propertyFieldId = (definitionId: number) => `property:${definitionId}`;

/** Anything a view can show about an item. */
export type FieldDef = {
  id: string;
  kind: FieldKind;
  source: "builtin" | "property" | "plugin";
  /** Built-in: an i18n key, in `projects` unless it names its namespace.
   *  Property or plug-in field: its own name, untranslated. */
  label: string;
  /** What the field holds for an item. Nothing (null, "", []) draws nothing on
   *  a card; a cell says so. */
  value: (item: ViewItem) => unknown;
  /** A title cannot be hidden: a card with no title is not a card. */
  hideable: boolean;
  /** A plug-in field's install and declaration. */
  plugin?: { install: number; field: PluginFieldDecl };
  /** The sentence the value sits in, as an i18n key ("Due: {{date}}"). */
  phrase?: string;
  icon?: LucideIcon;
  tone?: "warning";
  /** How a cell marks a date that has passed: as begun, or as overdue until
   *  the item is done. */
  past?: "primary" | "destructive";
};

/** What renderers share across a view. It changes with the language, the
 *  community and the item links, not with which fields are shown, so a renderer
 *  whose value is unchanged skips redrawing when the Fields menu changes. */
export type ViewEnv = {
  /** Reads `projects`, and the other {@link VIEW_NAMESPACES} by prefix. */
  t: TranslateFn;
  /** A community-relative path, made absolute in the item's community. */
  communityPath: (path: string, item: ViewItem) => string;
  taskHref: (task: ViewItem) => string;
};

export const VIEW_NAMESPACES = ["projects", "tasks", "dates", "relations"] as const;

/** The env of a project's views: one community, and its tasks' pages. */
export const useProjectViewEnv = (taskHref: (taskId: number) => string): ViewEnv => {
  const { t } = useTranslation(VIEW_NAMESPACES);
  const communityPath = useCommunityPath();
  return useMemo(
    () => ({ t: t as TranslateFn, communityPath, taskHref: (task) => taskHref(task.id) }),
    [t, communityPath, taskHref]
  );
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

// A table's title cell carries what the card shows as fields of their own.
const TitleCell = ({
  title,
  task,
  unread,
  env,
}: {
  title: string;
  task: ViewItem;
  unread: boolean;
  env: ViewEnv;
}) => {
  const recurrence = task.recurrence
    ? summarizeStored(
        task.recurrence,
        task.due_date || task.start_date,
        { strategy: task.recurrence_strategy, shift: task.recurrence_shift },
        env.t
      )
    : null;
  return (
    <div className="flex items-center gap-2">
      <div className="flex w-full min-w-60 flex-col items-start text-left">
        <Link
          to={env.taskHref(task)}
          draggable={false}
          className="flex items-center gap-2 rounded-sm font-medium underline-offset-4 outline-none hover:underline focus-visible:ring-1 focus-visible:ring-ring"
        >
          {title}
          {unread ? <UnreadDot /> : null}
        </Link>
        <div className="space-y-1 text-muted-foreground text-xs">
          {task.assignees.length > 0 ? (
            <TaskAssigneeList assignees={task.assignees} className="text-xs" />
          ) : null}
          {recurrence ? <p>{truncateText(recurrence, 100)}</p> : null}
        </div>
        <TaskChecklistProgress progress={task.checklist_progress} className="mt-2 max-w-[200px]" />
      </div>
      <TaskBlockersHoverCard task={task} />
      <TaskDescriptionHoverCard task={task} />
    </div>
  );
};

// Only the title opens the task: the rest of the card is the card, and a real
// link means middle-click and "open in new tab" work.
const TitleField = ({ value, item, variant, env }: FieldRendererProps) => {
  const unread = useUnreadTree().hasSubject(item.community_id, "task", item.id);
  if (variant === "cell") {
    return <TitleCell title={value as string} task={item} unread={unread} env={env} />;
  }
  return (
    <Link
      to={env.taskHref(item)}
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
// 12/24-hour choice. A cell says how far off the date is instead.
const DateField = ({ value, item, field, variant, env }: FieldRendererProps) => {
  if (variant === "cell") {
    return (
      <DateCell
        date={value as string | null}
        isPastVariant={field.past}
        isDone={item.task_status?.category === "done"}
      />
    );
  }
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

const CountField = ({ value, field, variant, env }: FieldRendererProps) => {
  const count = value as number | null;
  const Icon = field.icon;
  if (variant === "cell") {
    return count ? (
      <span className="inline-flex items-center gap-1 text-sm">
        {Icon ? <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" /> : null}
        {count}
      </span>
    ) : (
      <span className="text-muted-foreground text-sm">0</span>
    );
  }
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

const TagsField = ({ value, item, variant, env }: FieldRendererProps) => {
  const tags = value as TagSummary[];
  const tagHref = (tag: TagSummary) => env.communityPath(`/tags/${tag.id}`, item);
  if (variant === "cell") {
    return tags.length > 0 ? (
      <TagBadgeList tags={tags} tagHref={tagHref} />
    ) : (
      <span className="text-muted-foreground text-sm">&mdash;</span>
    );
  }
  return tags.map((tag) => <TagBadge key={tag.id} tag={tag} size="sm" to={tagHref(tag)} />);
};

const PropertyField = ({ value, variant }: FieldRendererProps) => (
  <PropertyValueCell
    summary={(value as PropertySummary | null) ?? undefined}
    variant={variant === "cell" ? "cell" : "chip"}
  />
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
  plugin: memo(PluginField),
};
