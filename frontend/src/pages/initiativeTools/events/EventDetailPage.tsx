import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { Copy, Loader2, MoreHorizontal, Trash2, Unlink } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type CalendarEventRead,
  SearchEntityType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { isRepeating, occurrenceTarget } from "@/components/calendar/eventCalendarEntry";
import { ModerationMenu } from "@/components/moderation/ModerationMenu";
import { ReportButton } from "@/components/moderation/ReportButton";
import { useScopePrompt } from "@/components/recurrence/OccurrenceScopeDialog";
import { DetailPageSkeleton, SkeletonRegion } from "@/components/skeletons/PageSkeletons";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";
import { ToolBreadcrumb } from "@/components/tools/ToolBreadcrumb";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  useCalendarEvent,
  useDeleteCalendarEvent,
  useDuplicateCalendarEvent,
  useOccurrenceAction,
} from "@/hooks/useCalendarEvents";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useInitiative } from "@/hooks/useInitiatives";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { useRecordOpen } from "@/hooks/useRecents";
import { useCommunityPath } from "@/lib/communityUrl";
import { toast } from "@/lib/mascotToast";
import { eventRoute, toolDetailRoute, toolListRoute } from "@/lib/tools";
import { EventPageView } from "@/lib/views/eventPage";

/**
 * An event's page: every field of it, each saved on its own where the reader
 * may change it, laid out as the task page is. A repeating event opened at
 * one of its dates shows that date, and a change to it asks which dates it is
 * for.
 */
export function EventDetailPage() {
  const { t } = useTranslation(["calendars", "common"]);
  const { eventId, calendarId: calendarIdParam } = useParams({ strict: false }) as {
    eventId: string;
    calendarId?: string;
  };
  // Opened from a calendar, a repeating event names the occurrence it was.
  const { occurrence: occurrenceParam } = useSearch({ strict: false }) as { occurrence?: string };
  const occurrence =
    occurrenceParam && !Number.isNaN(Date.parse(occurrenceParam)) ? occurrenceParam : undefined;
  const calendarId = calendarIdParam ? Number(calendarIdParam) : null;
  const parsedId = Number(eventId);
  const navigate = useNavigate();
  const gp = useCommunityPath();

  const eventQuery = useCalendarEvent(
    Number.isFinite(parsedId) ? parsedId : null,
    undefined,
    occurrence
  );
  const event = eventQuery.data;
  useReadOnOpen("calendar_event", event?.id);
  useRecordOpen("calendar_event", event?.id);
  // The path supplies the initiative while this loads; the entity is the
  // authority once it arrives, and a URL naming a different one is corrected.
  const initiativeId = useCanonicalInitiativeId(event?.initiative_id);
  const leaveTo = gp(
    calendarId == null
      ? toolListRoute(Tool.calendar, initiativeId)
      : toolDetailRoute(Tool.calendar, initiativeId, calendarId)
  );

  // Set when the page is left on purpose, so an open draft does not hold it.
  const leaving = useRef(false);
  const leave = (to: string) => {
    leaving.current = true;
    void navigate({ to });
  };
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const deleteEvent = useDeleteCalendarEvent({
    onSuccess: () => {
      toast.success(t("eventDeleted"));
      leave(leaveTo);
    },
  });
  const toEvent = (moved: Pick<CalendarEventRead, "id" | "calendar_id">) =>
    leave(gp(eventRoute(initiativeId, moved.calendar_id, moved.id)));
  const duplicateEvent = useDuplicateCalendarEvent({
    onSuccess: (copy) => {
      toast.success(t("common:subToolDuplicate.done"));
      toEvent(copy);
    },
  });
  const detach = useOccurrenceAction(event?.series_id ?? parsedId, "detach", {
    onSuccess: (detached) => {
      toast.success(t("occurrence.detached"));
      toEvent(detached);
    },
  });

  // A repeating event's occurrence, or one with a row of its own: a change
  // asks which occurrences it is for.
  const scopePrompt = useScopePrompt();

  // An event takes its level from its calendar; changing and deleting both ask
  // for write on it.
  const canWrite = Boolean(event?.can.edit);
  // Moderation is of initiative content, so an event on a community-level
  // calendar has no moderators to offer it to.
  const initiativeQuery = useInitiative(event?.initiative_id ?? null);
  const canModerate = event?.initiative_id != null && Boolean(initiativeQuery.data?.can.moderate);

  if (eventQuery.isLoading) {
    return (
      <SkeletonRegion label={t("loadingEvent")}>
        <DetailPageSkeleton actions={2} />
      </SkeletonRegion>
    );
  }

  if (eventQuery.isError || !event) {
    return (
      <ToolAccessStatus
        error={eventQuery.error}
        keys="calendars:"
        backTo={leaveTo}
        backLabel={t("backToEvents")}
      />
    );
  }

  // The occurrence is the series at that start, with the series' length.
  const shownStart = event.recurrence && occurrence ? occurrence : event.start_at;
  const shownEnd = new Date(
    Date.parse(shownStart) + Date.parse(event.end_at) - Date.parse(event.start_at)
  ).toISOString();
  const repeating = isRepeating(event);
  // The occurrence a change here is about, by its start in the series.
  const occurrenceStart = event.original_start ?? shownStart;

  const handleDelete = async () => {
    if (!repeating) {
      setDeleteConfirmOpen(true);
      return;
    }
    const scope = await scopePrompt.ask("delete");
    if (scope) {
      deleteEvent.mutate({ eventId: parsedId, ...occurrenceTarget(event, scope, occurrenceStart) });
    }
  };

  // Opened at one date of a repeating event: that date alone, or the series.
  const handleDuplicate = async () => {
    const scope =
      event.recurrence && occurrence
        ? await scopePrompt.ask("duplicate", { scopes: ["this", "all"] })
        : "all";
    if (scope)
      duplicateEvent.mutate({
        eventId: parsedId,
        occurrence: scope === "this" ? occurrenceStart : undefined,
      });
  };

  const menuPending = duplicateEvent.isPending || detach.isPending;
  const actions = (
    <div className="flex items-center gap-1">
      <ReportButton
        targetType={SearchEntityType.calendar_event}
        targetId={event.id}
        authorId={event.created_by}
      />
      <ModerationMenu
        targetType={SearchEntityType.calendar_event}
        targetId={event.id}
        canModerate={canModerate}
        communityId={event.community_id}
        onGone={() => leave(leaveTo)}
      />
      {canWrite ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="outline"
              size="icon"
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
            <DropdownMenuItem
              disabled={duplicateEvent.isPending}
              onSelect={() => void handleDuplicate()}
            >
              <Copy className="h-4 w-4" />
              {t("common:subToolDuplicate.action")}
            </DropdownMenuItem>
            {repeating ? (
              <DropdownMenuItem
                disabled={detach.isPending}
                onSelect={() => detach.mutate(occurrenceStart)}
              >
                <Unlink className="h-4 w-4" />
                {t("occurrence.detach")}
              </DropdownMenuItem>
            ) : null}
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive focus:text-destructive"
              disabled={deleteEvent.isPending}
              onSelect={() => void handleDelete()}
            >
              <Trash2 className="h-4 w-4" />
              {t("deleteEvent")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </div>
  );

  return (
    <div className="space-y-6">
      <ToolBreadcrumb tool={Tool.calendar} initiativeId={initiativeId} trail={[]} />
      <EventPageView
        event={event}
        page={{
          readOnly: !canWrite,
          initiativeId,
          occurrence,
          occurrenceStart,
          shownStart,
          shownEnd,
          askScope: (action) => scopePrompt.ask(action),
          onMoved: toEvent,
          onShifted: (start) =>
            void navigate({
              to: gp(eventRoute(initiativeId, event.calendar_id, event.id)),
              search: { occurrence: start },
              replace: true,
            }),
          leaving,
          actions,
        }}
      />
      <ConfirmDialog
        open={deleteConfirmOpen}
        onOpenChange={setDeleteConfirmOpen}
        title={t("deleteEvent")}
        description={t("deleteEventConfirm")}
        confirmLabel={t("deleteEvent")}
        cancelLabel={t("common:cancel")}
        onConfirm={() => deleteEvent.mutate({ eventId: parsedId })}
        isLoading={deleteEvent.isPending}
        destructive
      />
      {scopePrompt.dialog}
    </div>
  );
}
