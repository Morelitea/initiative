import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { CalendarDays, MapPin, Repeat, Trash2, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { type RSVPStatus, SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import { PropertyValueCell } from "@/components/properties/PropertyValueCell";
import { iconForPropertyType } from "@/components/properties/propertyTypeIcons";
import {
  type OccurrenceScope,
  useScopePrompt,
} from "@/components/recurrence/OccurrenceScopeDialog";
import { DetailPageSkeleton, SkeletonRegion } from "@/components/skeletons/PageSkeletons";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";
import { ToolPageHeader } from "@/components/tools/ToolPageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/hooks/useAuth";
import {
  useCalendarEvent,
  useDeleteCalendarEvent,
  useOccurrenceAction,
  useUpdateEventRSVP,
} from "@/hooks/useCalendarEvents";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { toast } from "@/lib/chesterToast";
import { useGuildPath } from "@/lib/guildUrl";
import { summarizeStored } from "@/lib/recurrence";
import { hour12Option } from "@/lib/timeFormat";
import { eventRoute, eventSettingsRoute, toolDetailRoute, toolListRoute } from "@/lib/tools";
import { getUserDisplayName } from "@/lib/userDisplay";
import type { TranslateFn } from "@/types/i18n";

const RSVP_LABEL_KEYS: Record<
  string,
  "rsvpPending" | "rsvpAccepted" | "rsvpDeclined" | "rsvpTentative"
> = {
  pending: "rsvpPending",
  accepted: "rsvpAccepted",
  declined: "rsvpDeclined",
  tentative: "rsvpTentative",
};

const rsvpLabelKey = (status: string) => RSVP_LABEL_KEYS[status] ?? "rsvpPending";

/**
 * Format a datetime string for display.
 * Uses Intl.DateTimeFormat for locale-aware formatting.
 */
const formatDateTime = (dateStr: string, allDay: boolean): string => {
  const date = new Date(dateStr);

  if (allDay) {
    // An all-day event's date is its UTC date, the same for every viewer.
    return date.toLocaleDateString(undefined, {
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric",
      timeZone: "UTC",
    });
  }

  return date.toLocaleString(undefined, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: hour12Option(),
  });
};

/**
 * Format a date range for display.
 */
const formatDateRange = (startStr: string, endStr: string, allDay: boolean): string => {
  const start = new Date(startStr);
  const end = new Date(endStr);

  if (allDay) {
    const startDate = formatDateTime(startStr, true);
    const endDate = formatDateTime(endStr, true);
    if (startDate === endDate) return startDate;
    return `${startDate} - ${endDate}`;
  }

  const sameDay =
    start.getFullYear() === end.getFullYear() &&
    start.getMonth() === end.getMonth() &&
    start.getDate() === end.getDate();

  if (sameDay) {
    const dayPart = start.toLocaleDateString(undefined, {
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric",
    });
    const startTime = start.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
      hour12: hour12Option(),
    });
    const endTime = end.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
      hour12: hour12Option(),
    });
    return `${dayPart}, ${startTime} - ${endTime}`;
  }

  return `${formatDateTime(startStr, false)} - ${formatDateTime(endStr, false)}`;
};

/** Map RSVP status to a badge variant */
const rsvpBadgeVariant = (
  status: RSVPStatus
): "default" | "secondary" | "destructive" | "outline" => {
  switch (status) {
    case "accepted":
      return "default";
    case "declined":
      return "destructive";
    case "tentative":
      return "outline";
    default:
      return "secondary";
  }
};

export function EventDetailPage() {
  const { t } = useTranslation(["calendars", "common", "dates"]);
  const { eventId, calendarId: calendarIdParam } = useParams({ strict: false }) as {
    eventId: string;
    calendarId?: string;
  };
  // Opened from a calendar, a repeating event names the occurrence it was.
  const { occurrence } = useSearch({ strict: false }) as { occurrence?: string };
  const calendarId = calendarIdParam ? Number(calendarIdParam) : null;
  const parsedId = Number(eventId);
  const navigate = useNavigate();
  const gp = useGuildPath();
  const { user } = useAuth();

  const eventQuery = useCalendarEvent(
    Number.isFinite(parsedId) ? parsedId : null,
    undefined,
    occurrence
  );
  const event = eventQuery.data;
  useReadOnOpen("calendar_event", event?.id);
  // The path supplies the initiative while this loads; the entity is the
  // authority once it arrives, and a URL naming a different one is corrected.
  const initiativeId = useCanonicalInitiativeId(event?.initiative_id);

  // Delete event
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const deleteEvent = useDeleteCalendarEvent({
    onSuccess: () => {
      toast.success(t("eventDeleted"));
      void navigate({
        to: gp(
          calendarId == null
            ? toolListRoute(Tool.calendar, initiativeId)
            : toolDetailRoute(Tool.calendar, initiativeId, calendarId)
        ),
      });
    },
  });

  // RSVP
  const updateRSVP = useUpdateEventRSVP(parsedId, {
    onSuccess: () => {
      toast.success(t("rsvpUpdated"));
    },
  });

  // A repeating event's occurrence, or one with a row of its own: a change
  // asks which occurrences it is for.
  const scopePrompt = useScopePrompt();
  const seriesId = event?.series_id ?? parsedId;
  const toEvent = (id: number) =>
    void navigate({ to: gp(eventRoute(initiativeId, event?.calendar_id ?? 0, id)) });
  const openAlone = useOccurrenceAction(seriesId, "open", {
    onSuccess: (opened) => toEvent(opened.id),
  });
  const detach = useOccurrenceAction(seriesId, "detach", {
    onSuccess: (detached) => {
      toast.success(t("occurrence.detached"));
      toEvent(detached.id);
    },
  });

  // An event takes its level from its calendar; editing and deleting both ask
  // for write on it.
  const canWrite = Boolean(event?.can.edit);

  // Find current user's RSVP status
  const myAttendee = useMemo(() => {
    if (!event || !user) return null;
    return event.attendees.find((a) => a.user_id === user.id) ?? null;
  }, [event, user]);

  const myRsvpStatus = myAttendee?.rsvp_status ?? null;

  // Error / loading states
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
        backTo={gp(
          calendarId == null
            ? toolListRoute(Tool.calendar, initiativeId)
            : toolDetailRoute(Tool.calendar, initiativeId, calendarId)
        )}
        backLabel={t("backToEvents")}
      />
    );
  }

  // The occurrence is the series at that start, with the series' length.
  const shownStart =
    event.recurrence && occurrence && !Number.isNaN(Date.parse(occurrence))
      ? occurrence
      : event.start_at;
  const repeating = Boolean(event.recurrence) || event.series_id != null;
  // The occurrence a change here is about, by its start in the series.
  const occurrenceStart = event.original_start ?? shownStart;
  const scoped = (scope: OccurrenceScope) =>
    event.series_id != null ? { scope } : { scope, occurrence: occurrenceStart };

  const handleDelete = async () => {
    if (!repeating) {
      setDeleteConfirmOpen(true);
      return;
    }
    const scope = await scopePrompt.ask("delete");
    if (scope) deleteEvent.mutate({ eventId: parsedId, ...scoped(scope) });
  };

  // An answer is for one event: a series' is for the occurrence shown.
  const handleAnswer = (status: RSVPStatus) =>
    updateRSVP.mutate({
      rsvp_status: status,
      ...(event.recurrence ? { occurrence: occurrenceStart } : {}),
    });
  const shownEnd = new Date(
    Date.parse(shownStart) + Date.parse(event.end_at) - Date.parse(event.start_at)
  ).toISOString();

  return (
    <div className="space-y-6">
      <ToolPageHeader
        tool={Tool.calendar}
        initiativeId={initiativeId}
        settingsTo={
          canWrite ? eventSettingsRoute(initiativeId, event.calendar_id, event.id) : undefined
        }
        settingsSearch={event.recurrence && occurrence ? { occurrence } : undefined}
        title={event.title}
      >
        {event.description && <p className="text-muted-foreground text-sm">{event.description}</p>}
        {event.all_day || canWrite ? (
          <div className="flex flex-wrap items-center gap-2">
            {event.all_day && <Badge variant="secondary">{t("allDay")}</Badge>}
            {canWrite && repeating && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => detach.mutate(occurrenceStart)}
                disabled={detach.isPending}
              >
                {t("occurrence.detach")}
              </Button>
            )}
            {canWrite && (
              <Button
                variant="outline"
                size="sm"
                className="text-destructive hover:text-destructive"
                onClick={() => void handleDelete()}
              >
                <Trash2 className="h-4 w-4" />
                {t("common:delete")}
              </Button>
            )}
          </div>
        ) : null}
      </ToolPageHeader>

      {/* Date, time, and location details */}
      <Card>
        <CardContent className="space-y-4 pt-6">
          <div className="flex items-start gap-3">
            <CalendarDays className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
            <div>
              <p className="font-medium">{formatDateRange(shownStart, shownEnd, event.all_day)}</p>
            </div>
          </div>

          {event.recurrence && (
            <div className="flex items-start gap-3">
              <Repeat className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
              <div className="space-y-1 text-sm">
                <p>
                  {summarizeStored(
                    event.recurrence,
                    event.start_at,
                    { shift: event.recurrence_shift, allDay: event.all_day },
                    t as TranslateFn
                  )}
                </p>
                {canWrite && occurrence && (
                  <Button
                    variant="link"
                    className="h-auto p-0"
                    onClick={() => openAlone.mutate(occurrenceStart)}
                    disabled={openAlone.isPending}
                  >
                    {t("occurrence.openAlone")}
                  </Button>
                )}
              </div>
            </div>
          )}

          {event.series_id != null && (
            <div className="flex items-start gap-3">
              <Repeat className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
              <div className="space-y-1 text-sm">
                <p>{t("occurrence.partOfSeries")}</p>
                <Link
                  className="text-primary underline-offset-4 hover:underline"
                  to={gp(eventRoute(initiativeId, event.calendar_id, event.series_id))}
                >
                  {t("occurrence.openSeries")}
                </Link>
              </div>
            </div>
          )}

          {event.location && (
            <div className="flex items-start gap-3">
              <MapPin className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
              <p className="text-sm">{event.location}</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* RSVP section */}
      {myAttendee && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-lg">{t("rsvp")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-4">
              <Select
                // Pending is no answer yet, so it shows as the placeholder
                // rather than as a choice.
                value={myRsvpStatus === "pending" ? "" : (myRsvpStatus ?? "")}
                onValueChange={(value) => handleAnswer(value as RSVPStatus)}
                disabled={updateRSVP.isPending}
              >
                <SelectTrigger className="w-[140px]">
                  <SelectValue placeholder={t("rsvpPending")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="accepted">{t("rsvpAccepted")}</SelectItem>
                  <SelectItem value="tentative">{t("rsvpTentative")}</SelectItem>
                  <SelectItem value="declined">{t("rsvpDeclined")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Attendees list */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg">
            <div className="flex items-center gap-2">
              <Users className="h-5 w-5" />
              {t("attendees")} ({event.attendees.length})
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {event.attendees.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("noAttendees")}</p>
          ) : (
            <div className="space-y-2">
              {event.attendees.map((attendee) => (
                <div
                  key={attendee.user_id}
                  className="flex items-center justify-between rounded-md border px-3 py-2"
                >
                  <span className="font-medium text-sm">
                    {getUserDisplayName(attendee.user ?? { id: attendee.user_id })}
                  </span>
                  <Badge variant={rsvpBadgeVariant(attendee.rsvp_status)}>
                    {t(rsvpLabelKey(attendee.rsvp_status))}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Tags */}
      {event.tags.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-lg">{t("tags")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {event.tags.map((tag) => (
                <Badge
                  key={tag.id}
                  variant="outline"
                  style={{
                    borderColor: tag.color,
                    color: tag.color,
                  }}
                >
                  {tag.name}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* What it is connected to, between what it is labelled with and what
          it records — the order the task page reads in. */}
      <ToolRelationsPanel
        tool={Tool.calendar}
        entity={event}
        target={{ type: SearchEntityType.calendar_event, id: parsedId }}
        canEdit={canWrite}
        entityTitle={event.title}
      />

      {/* Custom Properties — read-only view; edits happen on the Settings page. */}
      {event.properties.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-lg">{t("properties")}</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {event.properties.map((property) => {
                const Icon = iconForPropertyType(property.type);
                return (
                  <li
                    key={property.property_id}
                    className="grid grid-cols-[minmax(0,8rem)_1fr] items-center gap-2"
                  >
                    <span className="flex min-w-0 items-center gap-1.5 font-normal text-muted-foreground text-xs">
                      <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
                      <span className="truncate">{property.name}</span>
                    </span>
                    <PropertyValueCell summary={property} variant="cell" />
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* Delete Event Confirmation */}
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
