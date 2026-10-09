/**
 * The task sections' parts: the components Tavern's task templates place.
 *
 * Each draws one piece and nothing around it. Where it sits, and whether it is
 * there at all, is the template's (themes/tavern/sections/task.*.html).
 */

import { Link } from "@tanstack/react-router";
import { Ban, MessageSquare } from "lucide-react";

import { UnreadDot } from "@/components/notifications/UnreadDot";
import { priorityVariant } from "@/components/projects/projectTasksConfig";
import { TaskAssigneeList } from "@/components/projects/TaskAssigneeList";
import { PropertyValueCell } from "@/components/properties/PropertyValueCell";
import { nonEmptyPropertySummaries } from "@/components/properties/propertyHelpers";
import { TagBadge } from "@/components/tags";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { Badge } from "@/components/ui/badge";
import { MentionText } from "@/components/user/MentionText";
import { useUnreadTree } from "@/hooks/useUnreadTree";
import { useCommunityPath } from "@/lib/communityUrl";
import { formatDateTime } from "@/lib/formatDate";
import { summarizeStored } from "@/lib/recurrence";
import type { PartProps, PartsFor } from "@/lib/templates/sections";
import { truncateText } from "@/lib/text";
import { cn } from "@/lib/utils";

type CardProps = PartProps<"task.card">;

const CardTitle = ({ data: { task }, context, className }: CardProps) => {
  const unread = useUnreadTree().hasSubject(task.community_id, "task", task.id);
  const dot = unread ? <UnreadDot className="ml-2 inline-block align-middle" /> : null;
  if (context.taskHref === null) {
    return (
      <p className={cn("font-medium", className)}>
        {task.title}
        {dot}
      </p>
    );
  }
  // A real link, so middle-click and "open in new tab" work. Not draggable, so
  // picking the card up by its title drags the card.
  return (
    <Link
      to={context.taskHref(task.id)}
      draggable={false}
      className={cn(
        "wrap-break-word block w-full min-w-0 rounded-sm font-medium underline-offset-4 outline-none hover:underline focus-visible:ring-1 focus-visible:ring-ring",
        className
      )}
    >
      {task.title}
      {dot}
    </Link>
  );
};

const CardDescription = ({ data: { task }, context, className }: CardProps) => (
  <p className={className}>
    <MentionText text={task.description_excerpt ?? ""} disableLink={context.taskHref === null} />
  </p>
);

const CardAssignees = ({ data: { task }, className }: CardProps) => (
  <TaskAssigneeList assignees={task.assignees} className={cn("text-xs", className)} />
);

// `formatDateTime`, as every timestamp in the app: it honours the reader's
// 12/24-hour choice.
const CardStartDate = ({ data: { task }, context: { t }, className }: CardProps) => (
  <p className={className}>{t("kanban.starts", { date: formatDateTime(task.start_date) })}</p>
);

const CardDueDate = ({ data: { task }, context: { t }, className }: CardProps) => (
  <p className={className}>{t("kanban.due", { date: formatDateTime(task.due_date) })}</p>
);

const CardRecurrence = ({ data: { task }, context: { t }, className }: CardProps) => {
  if (!task.recurrence) return null;
  const summary = summarizeStored(
    task.recurrence,
    task.due_date || task.start_date,
    { strategy: task.recurrence_strategy, shift: task.recurrence_shift },
    t
  );
  return summary ? <p className={className}>{truncateText(summary, 80)}</p> : null;
};

const CardChecklist = ({ data: { task }, className }: CardProps) => (
  <TaskChecklistProgress progress={task.checklist_progress} className={className} />
);

const CardPriority = ({ data: { task }, context: { t }, className }: CardProps) => (
  <Badge variant={priorityVariant[task.priority]} className={className}>
    {t("kanban.priority", { priority: task.priority.replace("_", " ") })}
  </Badge>
);

const CardComments = ({ data: { task }, className }: CardProps) => (
  <Badge variant="outline" className={cn("inline-flex items-center gap-1 text-xs", className)}>
    <MessageSquare className="h-3.5 w-3.5" aria-hidden="true" />
    {task.comment_count}
  </Badge>
);

/**
 * The signal the retired Blocked column used to give, keeping itself current:
 * it goes when the last thing holding this up is finished.
 */
const CardBlockers = ({ data: { task }, context: { t }, className }: CardProps) => {
  const count = task.blocked_by_open_count ?? 0;
  return (
    <Badge
      variant="outline"
      className={cn(
        "inline-flex items-center gap-1 border-warning/40 text-warning text-xs",
        className
      )}
      title={t("relations:blockers.label", { count })}
    >
      <Ban className="h-3.5 w-3.5" aria-hidden="true" />
      {count}
    </Badge>
  );
};

/** Chips, each its own element, so the template's classes have nowhere to go. */
const CardTags = ({ data: { task }, context }: CardProps) => {
  const gp = useCommunityPath();
  return (task.tags ?? []).map((tag) => (
    <TagBadge
      key={tag.id}
      tag={tag}
      size="sm"
      to={context.taskHref === null ? undefined : gp(`/tags/${tag.id}`)}
    />
  ));
};

/** A property is turned off by its own entry in the Fields menu, by id. */
const CardProperties = ({ data: { task }, context }: CardProps) =>
  nonEmptyPropertySummaries(task.properties)
    .filter((summary) => context.showsProperty(summary.property_id))
    .map((summary) => (
      <PropertyValueCell key={summary.property_id} summary={summary} variant="chip" />
    ));

export const taskCardParts: PartsFor<"task.card"> = {
  title: CardTitle,
  description: CardDescription,
  assignees: CardAssignees,
  startDate: CardStartDate,
  dueDate: CardDueDate,
  recurrence: CardRecurrence,
  checklist: CardChecklist,
  priority: CardPriority,
  comments: CardComments,
  blockers: CardBlockers,
  tags: CardTags,
  properties: CardProperties,
};
