/**
 * The task sections' parts: the components Tavern's task templates place.
 *
 * Each draws one piece and nothing around it. Where it sits, and whether it is
 * there at all, is the template's (themes/tavern/sections/task.*.html).
 */

import { Link } from "@tanstack/react-router";
import {
  Archive,
  ArchiveRestore,
  Ban,
  Copy,
  FolderInput,
  Loader2,
  MessageSquare,
  MoreHorizontal,
  Save,
  SkipForward,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";

import type { TaskStatusRead } from "@/api/generated/initiativeAPI.schemas";
import { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { CommentSection } from "@/components/comments/CommentSection";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import { MentionComposer } from "@/components/markdown/MentionComposer";
import { UnreadDot } from "@/components/notifications/UnreadDot";
import { priorityVariant } from "@/components/projects/projectTasksConfig";
import { TaskAssigneeList } from "@/components/projects/TaskAssigneeList";
import { PropertyValueCell } from "@/components/properties/PropertyValueCell";
import { nonEmptyPropertySummaries } from "@/components/properties/propertyHelpers";
import { TagBadge } from "@/components/tags";
import { TaskChecklist } from "@/components/tasks/TaskChecklist";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { TaskDescription } from "@/components/tasks/TaskDescription";
import {
  TaskAssigneesField,
  TaskDatesField,
  type TaskFormValue,
  TaskPriorityField,
  TaskPropertiesField,
  TaskRecurrenceField,
  TaskStatusField,
  TaskTagsField,
  TaskTitleField,
} from "@/components/tasks/TaskForm";
import { CasePanel } from "@/components/tickets/CasePanel";
import { ToolBreadcrumb } from "@/components/tools/ToolBreadcrumb";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { MentionText } from "@/components/user/MentionText";
import type { useComments, useCommentsCache } from "@/hooks/useComments";
import { usePastedImages } from "@/hooks/usePastedImages";
import { useUnreadTree } from "@/hooks/useUnreadTree";
import { useCommunityPath } from "@/lib/communityUrl";
import { formatDateTime } from "@/lib/formatDate";
import { summarizeStored } from "@/lib/recurrence";
import { referenceRef } from "@/lib/smartChips";
import type { PartProps, PartsFor } from "@/lib/templates/sections";
import { truncateText } from "@/lib/text";
import { toolDetailRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

/** What a board shares with each of its cards. */
export interface TaskCardContext {
  /** Where a card's title leads; null on the card being dragged, which leads nowhere. */
  taskHref: ((taskId: number) => string) | null;
  /** Whether the reader shows a property on cards, by the property's id. */
  showsProperty: (propertyId: number) => boolean;
  /** The board's translations (projects, dates, relations), so no card asks for its own. */
  t: (key: string, options?: Record<string, unknown>) => string;
}

/** Something the task page can do, and whether it is under way. */
interface PageAction {
  run: () => void;
  pending: boolean;
}

/**
 * What the task page shares with its parts: the edit in progress, and what can
 * be done with the task. The page owns all of it; a part only reads it.
 */
export interface TaskPageContext {
  /** The fields as edited, and the change to them. */
  form: { values: TaskFormValue; set: (patch: Partial<TaskFormValue>) => void };
  /**
   * The id of the page's `<form>`, which the actions part draws. A field with
   * typed inputs names it (`<input form>`), so Enter in one saves the task and
   * the browser's own checks hold the save back.
   */
  formId: string;
  /** Why the reader cannot edit, or null when they can. */
  readOnlyMessage: string | null;
  readOnly: boolean;
  /** The project's statuses, with the task's own when the project dropped it. */
  statuses: TaskStatusRead[];
  project: { id: number; name: string; initiative_id: number } | null;
  /** The initiative the page is addressed under. */
  initiativeId: number | null;
  currentUserId?: number;
  /** Who made the task and when, for the byline. */
  creation: {
    displayName: string | null;
    avatarSrc?: string;
    anonymized: boolean;
    initials: string;
    creatorId: number | null;
    relative: string | null;
    absolute: string;
  } | null;
  save: {
    submit: (event: FormEvent<HTMLFormElement>) => void;
    pending: boolean;
    /** The dates are the wrong way round, so the edit cannot be saved. */
    blocked: boolean;
  };
  cancel: () => void;
  menu: {
    move: PageAction;
    duplicate: PageAction;
    archive: PageAction & { archived: boolean };
    /** Only for a repeating task. */
    skip: PageAction | null;
    remove: PageAction;
  };
  /** Writing the description for the reader, when the community allows it. */
  describe: PageAction | null;
  comments: {
    query: ReturnType<typeof useComments>;
    cache: ReturnType<typeof useCommentsCache>;
  };
}

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

type PageProps = PartProps<"task.page">;

const PageBreadcrumb = ({ context: { project, initiativeId } }: PageProps) => (
  <ToolBreadcrumb
    tool={Tool.project}
    initiativeId={initiativeId}
    trail={
      project
        ? [{ label: project.name, to: toolDetailRoute(Tool.project, initiativeId, project.id) }]
        : []
    }
  />
);

/** The title field is the page's heading; the h1 names it for a screen reader. */
const PageTitle = ({ data: { task }, context, className }: PageProps) => (
  <>
    <h1 className="sr-only">{context.form.values.title || task.title}</h1>
    <TaskTitleField
      value={context.form.values}
      onChange={context.form.set}
      disabled={context.readOnly}
      form={context.formId}
      className={className}
      inputClassName="h-auto font-semibold text-3xl tracking-tight shadow-none focus-visible:ring-0 sm:text-3xl"
    />
  </>
);

const PageByline = ({ context: { creation }, className }: PageProps) => {
  const { t } = useTranslation("tasks");
  if (!creation) return null;
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className={cn("flex items-center gap-2 text-muted-foreground text-xs", className)}>
            {creation.displayName ? (
              <Avatar className="h-5 w-5 border text-3xs">
                {creation.avatarSrc ? (
                  <AvatarImage src={creation.avatarSrc} alt={creation.displayName} />
                ) : null}
                <AvatarFallback userId={creation.anonymized ? null : creation.creatorId}>
                  {creation.initials}
                </AvatarFallback>
              </Avatar>
            ) : null}
            <span>
              {creation.displayName
                ? t("edit.createdBy", { name: creation.displayName, time: creation.relative })
                : t("edit.createdAt", { time: creation.relative })}
            </span>
          </div>
        </TooltipTrigger>
        <TooltipContent>{creation.absolute}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};

/** Why the reader cannot edit, when they cannot. */
const PageNotice = ({ context: { readOnlyMessage }, className }: PageProps) =>
  readOnlyMessage ? (
    <p
      className={cn(
        "rounded-md border border-border bg-muted/50 px-3 py-2 text-muted-foreground text-sm",
        className
      )}
    >
      {readOnlyMessage}
    </p>
  ) : null;

/** The description preview reads the way the saved one will. */
const renderDescription = (draft: string) => <TaskDescription content={draft} />;

const PageDescription = ({ data: { task }, context, className }: PageProps) => {
  const { t } = useTranslation("tasks");
  const uploadImage = usePastedImages();
  const { description } = context.form.values;
  return (
    <div className={cn("space-y-2", className)}>
      <Label htmlFor="task-description">{t("edit.descriptionLabel")}</Label>
      {context.readOnly ? (
        description ? (
          <div className="rounded-md border border-border/70 border-dashed bg-muted/40 px-3 py-2">
            <TaskDescription content={description} />
          </div>
        ) : (
          <p className="text-muted-foreground text-sm italic">{t("edit.noDescriptionReadOnly")}</p>
        )
      ) : (
        <MentionComposer
          id="task-description"
          value={description}
          onChange={(next) => context.form.set({ description: next })}
          initiativeId={context.initiativeId ?? 0}
          subject={referenceRef(SearchEntityType.task, task.id)}
          renderPreview={renderDescription}
          onUploadImage={uploadImage}
          defaultMode="preview"
          placeholder={t("edit.descriptionPlaceholder")}
          actions={
            context.describe ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 px-2 text-xs"
                onClick={context.describe.run}
                disabled={context.describe.pending}
              >
                {context.describe.pending ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Sparkles className="h-3 w-3" />
                )}
                {t("edit.aiGenerate")}
              </Button>
            ) : null
          }
        />
      )}
    </div>
  );
};

/** The form's value, setter and lock, as every field takes them. */
const fieldOf = (context: TaskPageContext, className?: string) => ({
  value: context.form.values,
  onChange: context.form.set,
  disabled: context.readOnly,
  className,
});

const PageStatus = ({ context, className }: PageProps) => (
  <TaskStatusField {...fieldOf(context, className)} statuses={context.statuses} />
);

const PagePriority = ({ context, className }: PageProps) => (
  <TaskPriorityField {...fieldOf(context, className)} />
);

const PageDates = ({ context, className }: PageProps) => (
  <TaskDatesField {...fieldOf(context, className)} />
);

const PageRecurrence = ({ data: { task }, context, className }: PageProps) => {
  const { dueDate, startDate } = context.form.values;
  return (
    <TaskRecurrenceField
      {...fieldOf(context, className)}
      form={context.formId}
      referenceDate={dueDate || startDate || task.due_date || task.start_date}
      stored={task.recurrence ? { rule: task.recurrence, shift: task.recurrence_shift ?? 0 } : null}
    />
  );
};

const PageAssignees = ({ data: { task }, context, className }: PageProps) => (
  <TaskAssigneesField
    {...fieldOf(context, className)}
    projectId={task.project_id}
    currentUserId={context.currentUserId}
    selectedAssignees={task.assignees}
  />
);

const PageTags = ({ context, className }: PageProps) => (
  <TaskTagsField {...fieldOf(context, className)} />
);

const PageProperties = ({ data: { task }, context, className }: PageProps) => (
  <TaskPropertiesField
    {...fieldOf(context, className)}
    form={context.formId}
    projectId={task.project_id}
    initiativeId={context.project?.initiative_id ?? null}
  />
);

/**
 * Save and Cancel, and everything else a task supports behind the overflow
 * menu, so the row stays readable at any width. The page's `<form>` is drawn
 * here, empty: the fields name it, so no form sits around anything else.
 */
const PageActions = ({ context, className }: PageProps) => {
  const { t } = useTranslation(["tasks", "common"]);
  const { save, menu } = context;
  // Duplicate, archive and skip dismiss the menu that holds their own pending
  // label, and none opens a dialog to carry one, so the trigger reports them.
  const menuPending = menu.duplicate.pending || menu.archive.pending || Boolean(menu.skip?.pending);
  return (
    <div className={className}>
      <form id={context.formId} onSubmit={save.submit} hidden />
      <Button
        type="submit"
        form={context.formId}
        disabled={save.pending || context.readOnly || save.blocked}
      >
        <Save className="h-4 w-4" />
        {save.pending ? t("edit.saving") : t("edit.saveTask")}
      </Button>
      <Button type="button" variant="outline" onClick={context.cancel}>
        <X className="h-4 w-4" />
        {t("common:cancel")}
      </Button>
      {!context.readOnly ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="ml-auto"
              aria-label={t("common:toolbar.moreActions")}
              aria-busy={menuPending}
            >
              {menuPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <MoreHorizontal className="h-4 w-4" />
              )}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem disabled={menu.move.pending} onSelect={menu.move.run}>
              <FolderInput className="h-4 w-4" />
              {t("edit.moveToProject")}
            </DropdownMenuItem>
            <DropdownMenuItem disabled={menu.duplicate.pending} onSelect={menu.duplicate.run}>
              <Copy className="h-4 w-4" />
              {menu.duplicate.pending ? t("edit.duplicating") : t("edit.duplicateTask")}
            </DropdownMenuItem>
            <DropdownMenuItem disabled={menu.archive.pending} onSelect={menu.archive.run}>
              {menu.archive.archived ? (
                <>
                  <ArchiveRestore className="h-4 w-4" />
                  {menu.archive.pending ? t("edit.unarchiving") : t("edit.unarchive")}
                </>
              ) : (
                <>
                  <Archive className="h-4 w-4" />
                  {menu.archive.pending ? t("edit.archiving") : t("edit.archive")}
                </>
              )}
            </DropdownMenuItem>
            {menu.skip ? (
              <DropdownMenuItem disabled={menu.skip.pending} onSelect={menu.skip.run}>
                <SkipForward className="h-4 w-4" />
                {t("edit.skipOccurrence")}
              </DropdownMenuItem>
            ) : null}
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive focus:text-destructive"
              disabled={menu.remove.pending}
              onSelect={menu.remove.run}
            >
              <Trash2 className="h-4 w-4" />
              {menu.remove.pending ? t("edit.deleting") : t("edit.deleteTask")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </div>
  );
};

const PageChecklist = ({ data: { task }, context }: PageProps) => (
  <TaskChecklist taskId={task.id} items={task.checklist ?? []} canEdit={!context.readOnly} />
);

/**
 * What the task is waiting on. A task is addressed inside its project, so
 * that is the tool a link refreshes.
 */
const PageRelations = ({ data: { task }, context }: PageProps) => (
  <ToolRelationsPanel
    tool={Tool.project}
    entity={{ id: task.project_id, initiative_id: task.project?.initiative_id ?? null }}
    target={{ type: SearchEntityType.task, id: task.id }}
    canEdit={!context.readOnly}
    entityTitle={task.title}
    defaultLayout="rows"
  />
);

const PageCase = ({ data: { task }, context }: PageProps) => (
  <CasePanel taskId={task.id} canEdit={!context.readOnly} />
);

const PageComments = ({ data: { task }, context }: PageProps) => {
  const { t } = useTranslation("tasks");
  const { query, cache } = context.comments;
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
        initiativeId={context.project?.initiative_id ?? 0}
      />
    </>
  );
};

export const taskPageParts: PartsFor<"task.page"> = {
  breadcrumb: PageBreadcrumb,
  title: PageTitle,
  byline: PageByline,
  notice: PageNotice,
  description: PageDescription,
  status: PageStatus,
  priority: PagePriority,
  dates: PageDates,
  recurrence: PageRecurrence,
  assignees: PageAssignees,
  tags: PageTags,
  properties: PageProperties,
  actions: PageActions,
  checklist: PageChecklist,
  relations: PageRelations,
  case: PageCase,
  comments: PageComments,
};
