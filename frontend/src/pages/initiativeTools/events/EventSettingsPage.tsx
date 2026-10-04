import { Link, useParams, useRouter, useSearch } from "@tanstack/react-router";
import { Loader2, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CalendarEventRead, TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { PropertyTarget, Tool } from "@/api/generated/initiativeAPI.schemas";
import { utcDateKey } from "@/components/calendar/eventCalendarEntry";
import {
  EventDateTimeFields,
  useEventTiming,
} from "@/components/initiativeTools/events/EventDateTimeFields";
import { toDateKey, toTimeSlotRounded } from "@/components/initiativeTools/events/eventDateTime";
import { MemberMultiSelect } from "@/components/members/MemberSearchSelect";
import { PropertyPanel } from "@/components/properties";
import { useScopePrompt } from "@/components/recurrence/OccurrenceScopeDialog";
import { RecurrenceEditor } from "@/components/recurrence/RecurrenceEditor";
import {
  DetailPageSkeleton,
  FormSkeleton,
  SkeletonRegion,
} from "@/components/skeletons/PageSkeletons";
import { TagPicker } from "@/components/tags";
import { ToolPageHeader } from "@/components/tools/ToolPageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  useCalendarEvent,
  useDeleteCalendarEvent,
  useOccurrenceAction,
  useSetEventAttendees,
  useUpdateCalendarEvent,
} from "@/hooks/useCalendarEvents";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useServerForm } from "@/hooks/useServerForm";
import { useCommunityPath } from "@/lib/communityUrl";
import { formatDate, formatDateTime } from "@/lib/formatDate";
import { toast } from "@/lib/mascotToast";
import { allDayReference, fromStored, rulePayload } from "@/lib/recurrence";
import { eventRoute, eventSettingsRoute, toolDetailRoute, toolListRoute } from "@/lib/tools";

export function EventSettingsPage() {
  const { t } = useTranslation(["calendars", "common", "access"]);
  const router = useRouter();
  const gp = useCommunityPath();
  const { eventId: eventIdParam, calendarId: calendarIdParam } = useParams({ strict: false }) as {
    eventId?: string;
    calendarId?: string;
  };
  const eventId = Number(eventIdParam);
  const calendarId = calendarIdParam ? Number(calendarIdParam) : null;
  // Opened from one occurrence of a repeating event, which a change names.
  const { occurrence: occurrenceParam } = useSearch({ strict: false }) as { occurrence?: string };
  const occurrence =
    occurrenceParam && !Number.isNaN(Date.parse(occurrenceParam)) ? occurrenceParam : undefined;

  const { data: event, isLoading } = useCalendarEvent(Number.isFinite(eventId) ? eventId : null);
  // The path supplies the initiative while this loads; the event is the
  // authority once it arrives, and null is a community-level calendar's address.
  const initiativeId = useCanonicalInitiativeId(event?.initiative_id);

  // Two cards, each with its own Save button — so two forms. One shared form
  // would let saving either card mark the other's unsaved edits as saved, and
  // the next refetch would take them away.
  const details = useServerForm(
    event,
    (loaded) => {
      // One occurrence of a series shows its own times: the series' length
      // from the start it has.
      const shift =
        loaded?.recurrence && occurrence ? Date.parse(occurrence) - Date.parse(loaded.start_at) : 0;
      const start = loaded ? new Date(Date.parse(loaded.start_at) + shift) : null;
      const end = loaded ? new Date(Date.parse(loaded.end_at) + shift) : null;
      return {
        title: loaded?.title ?? "",
        description: loaded?.description ?? "",
        location: loaded?.location ?? "",
        // An all-day event's dates are UTC dates.
        startDate: start
          ? loaded?.all_day
            ? utcDateKey(start.toISOString())
            : toDateKey(start)
          : "",
        startTime: start ? toTimeSlotRounded(start) : "09:00",
        endDate: end ? (loaded?.all_day ? utcDateKey(end.toISOString()) : toDateKey(end)) : "",
        endTime: end ? toTimeSlotRounded(end) : "10:00",
        allDay: loaded?.all_day ?? false,
      };
    },
    event?.id
  );
  // A rule is an object: compared by what it says, or every render would read
  // as news from the server.
  const repeat = useServerForm(
    event,
    (loaded) => ({
      rule: fromStored(
        loaded?.recurrence,
        loaded?.start_at,
        loaded?.recurrence_shift,
        loaded?.all_day
      ),
    }),
    event?.id,
    (a, b) => JSON.stringify(a) === JSON.stringify(b)
  );
  const attendees = useServerForm(
    event,
    (loaded) => ({ ids: loaded?.attendees.map((attendee) => attendee.user_id) ?? [] }),
    event?.id
  );
  const { title, description, location } = details.values;
  const attendeeIds = attendees.values.ids;
  const setTitle = (next: string) => details.set({ title: next });
  const setDescription = (next: string) => details.set({ description: next });
  const setLocation = (next: string) => details.set({ location: next });
  const setAttendeeIds = (next: number[]) => attendees.set({ ids: next });
  // Written the moment a tag is picked, so this one keeps following the server.
  const [tags, setTags] = useState<TagSummary[]>([]);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  // Attendee candidates come from whatever the event's calendar belongs to
  // (MemberMultiSelect below): every member of its initiative, or every member
  // of the community when the calendar belongs to no initiative. Event DAC (the
  // ShareControl below) is a separate concern tracked in #948. The current
  // attendees carry their own user summaries, so the chips render immediately.
  const attendeeUsers = useMemo(
    () => (event?.attendees ?? []).flatMap((a) => (a.user ? [a.user] : [])),
    [event?.attendees]
  );

  useEffect(() => {
    if (event) {
      setTags(event.tags ?? []);
    }
  }, [event]);

  const range = useEventTiming(details.values);

  const updateEvent = useUpdateCalendarEvent(eventId, {
    onSuccess: () => toast.success(t("detailsUpdated")),
  });

  const setAttendees = useSetEventAttendees(eventId, {
    onSuccess: () => toast.success(t("detailsUpdated")),
  });

  // Its own instance of the update, so a tag change saves without the
  // details toast.
  const saveTags = useUpdateCalendarEvent(eventId);

  // Tags persist immediately on change (like tasks/documents), no Save button.
  // Optimistically update, then roll back to the prior selection if the save
  // fails (the hook surfaces an error toast on its own).
  const handleTagsChange = (newTags: TagSummary[]) => {
    const previous = tags;
    setTags(newTags);
    saveTags.mutate(
      { tag_ids: newTags.map((tag) => tag.id) },
      { onError: () => setTags(previous) }
    );
  };

  const deleteEvent = useDeleteCalendarEvent({
    onSuccess: () => {
      toast.success(t("eventDeleted"));
      void router.navigate({
        to: gp(
          calendarId == null
            ? toolListRoute(Tool.calendar, initiativeId)
            : toolDetailRoute(Tool.calendar, initiativeId, calendarId)
        ),
      });
    },
  });

  // A change to a repeating event, or to one occurrence of it, asks which
  // occurrences it is for. "Just this" and "from here on" answer with another
  // row (the occurrence's own, or the new series), which the page moves to.
  const scopePrompt = useScopePrompt();
  const repeating = Boolean(event?.recurrence) || event?.series_id != null;
  const askScope = async (action: "edit" | "delete") => {
    if (!repeating) return {};
    const scope = await scopePrompt.ask(action);
    if (!scope) return null;
    return event?.series_id != null
      ? { scope }
      : { scope, occurrence: occurrence ?? event?.start_at };
  };
  const followRow = (saved: CalendarEventRead) => {
    if (saved.id !== eventId) {
      void router.navigate({
        to: gp(eventSettingsRoute(initiativeId, saved.calendar_id, saved.id)),
      });
    }
  };

  const handleSave = async () => {
    if (!range) return;
    // What is being sent, so anything changed while this is in flight is not
    // counted as saved by it.
    const sent = details.values;
    const target = await askScope("edit");
    if (target === null) return;
    updateEvent.mutate(
      {
        title: sent.title.trim() || undefined,
        description: sent.description.trim() || undefined,
        location: sent.location.trim() || undefined,
        ...range,
        all_day: sent.allDay,
        ...target,
      },
      {
        onSuccess: (saved) => {
          details.settle(sent);
          followRow(saved);
        },
      }
    );
  };

  const handleSaveRepeat = () => {
    const sent = repeat.values;
    if (sent.rule === "custom") return;
    updateEvent.mutate(rulePayload(sent.rule, { allDay: event?.all_day }), {
      onSuccess: () => repeat.settle(sent),
    });
  };

  const handleSaveAttendees = async () => {
    const sent = attendees.values;
    const target = await askScope("edit");
    if (target === null) return;
    setAttendees.mutate(
      { userIds: sent.ids, ...target },
      {
        onSuccess: (saved) => {
          attendees.settle(sent);
          followRow(saved);
        },
      }
    );
  };

  const handleDelete = async () => {
    if (!repeating) {
      setDeleteConfirmOpen(true);
      return;
    }
    const target = await askScope("delete");
    if (target) deleteEvent.mutate({ eventId, ...target });
  };

  // A series' skipped and extra dates.
  const restoreDate = useOccurrenceAction(eventId, "restore", {
    onSuccess: () => toast.success(t("occurrence.restored")),
  });
  const addDate = useOccurrenceAction(eventId, "add", {
    onSuccess: () => {
      toast.success(t("occurrence.added"));
      setExtraDate("");
    },
  });
  const [extraDate, setExtraDate] = useState("");

  if (isLoading) {
    return (
      <SkeletonRegion label={t("loadingEvent")}>
        <DetailPageSkeleton actions={0} description={false}>
          <FormSkeleton fields={5} />
        </DetailPageSkeleton>
      </SkeletonRegion>
    );
  }

  if (!event) {
    return (
      <div className="py-8 text-center">
        <p className="text-muted-foreground">{t("notFound")}</p>
        <Button variant="link" asChild className="mt-2">
          <Link to={gp(toolListRoute(Tool.calendar, initiativeId))}>{t("backToEvents")}</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <ToolPageHeader
        tool={Tool.calendar}
        initiativeId={initiativeId}
        trail={[{ label: event.title, to: eventRoute(initiativeId, event.calendar_id, eventId) }]}
        title={t("common:toolSettings.title")}
      />

      {/* Details */}
      <Card>
        <CardHeader>
          <CardTitle>{t("details")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="event-title">{t("eventTitle")}</Label>
            <Input id="event-title" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>

          <div className="space-y-2">
            <Label htmlFor="event-description">{t("description")}</Label>
            <Textarea
              id="event-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="event-location">{t("location")}</Label>
            <Input
              id="event-location"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
            />
          </div>

          <EventDateTimeFields value={details.values} onChange={details.set} />

          <Button onClick={() => void handleSave()} disabled={updateEvent.isPending || !range}>
            {updateEvent.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {t("saving")}
              </>
            ) : (
              t("common:save")
            )}
          </Button>
        </CardContent>
      </Card>

      {/* Attendees */}
      <Card>
        <CardHeader>
          <CardTitle>{t("repeat")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {event.series_id != null ? (
            <div className="space-y-1 text-sm">
              <p className="text-muted-foreground">{t("occurrence.followsSeries")}</p>
              <Link
                className="text-primary underline-offset-4 hover:underline"
                to={gp(eventSettingsRoute(initiativeId, event.calendar_id, event.series_id))}
              >
                {t("occurrence.openSeries")}
              </Link>
            </div>
          ) : (
            <>
              <RecurrenceEditor
                kind="event"
                value={repeat.values.rule}
                onChange={(rule) => repeat.set({ rule })}
                referenceDate={event.all_day ? allDayReference(event.start_at) : event.start_at}
                allDay={event.all_day}
                stored={
                  event.recurrence
                    ? { rule: event.recurrence, shift: event.recurrence_shift }
                    : null
                }
              />
              <Button
                onClick={handleSaveRepeat}
                disabled={
                  updateEvent.isPending || !repeat.edited || repeat.values.rule === "custom"
                }
              >
                {t("common:save")}
              </Button>
            </>
          )}

          {event.recurrence &&
            (
              [
                ["skipped", event.skipped_starts, true],
                ["extra", event.extra_starts, false],
              ] as const
            ).map(([kind, starts, restorable]) =>
              starts.length ? (
                <div key={kind} className="space-y-2">
                  <Label>{t(`occurrence.${kind}`)}</Label>
                  <ul className="space-y-1 text-sm">
                    {starts.map((start) => (
                      <li key={start} className="flex items-center justify-between gap-2">
                        <span>
                          {event.all_day ? formatDate(start.slice(0, 10)) : formatDateTime(start)}
                        </span>
                        {restorable ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => restoreDate.mutate(start)}
                            disabled={restoreDate.isPending}
                          >
                            {t("occurrence.restore")}
                          </Button>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null
            )}

          {event.recurrence ? (
            <div className="flex flex-wrap items-end gap-2">
              <div className="space-y-2">
                <Label className="sr-only">{t("occurrence.addDate")}</Label>
                <DateTimePicker
                  value={extraDate}
                  onChange={setExtraDate}
                  includeTime={!event.all_day}
                />
              </div>
              <Button
                variant="outline"
                disabled={!extraDate || addDate.isPending}
                onClick={() =>
                  addDate.mutate(
                    event.all_day
                      ? `${extraDate.slice(0, 10)}T00:00:00Z`
                      : new Date(extraDate).toISOString()
                  )
                }
              >
                {t("occurrence.addDate")}
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("attendees")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <MemberMultiSelect
            scope={{ type: "canOpen", tool: Tool.calendar, id: event?.calendar_id ?? null }}
            selectedIds={attendeeIds}
            selectedUsers={attendeeUsers}
            onChange={setAttendeeIds}
            placeholder={t("addAttendee")}
            emptyMessage={t("noAttendees")}
          />

          <Button onClick={() => void handleSaveAttendees()} disabled={setAttendees.isPending}>
            {setAttendees.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {t("saving")}
              </>
            ) : (
              t("common:save")
            )}
          </Button>
        </CardContent>
      </Card>

      {/* Tags */}
      <Card>
        <CardHeader>
          <CardTitle>{t("tags")}</CardTitle>
        </CardHeader>
        <CardContent>
          <TagPicker selectedTags={tags} onChange={handleTagsChange} />
        </CardContent>
      </Card>

      {/* Custom Properties — defined per initiative, so an event on a
          community-level calendar has none to offer. */}
      {event.initiative_id !== null && (
        <Card>
          <CardHeader>
            <CardTitle>{t("properties")}</CardTitle>
          </CardHeader>
          <CardContent>
            <PropertyPanel
              target={PropertyTarget.calendar_event}
              entityId={eventId}
              saved={event.properties}
              initiativeId={event.initiative_id}
              canOpen={{ tool: Tool.calendar, id: event.calendar_id }}
            />
          </CardContent>
        </Card>
      )}

      {/* Danger Zone */}
      <Card className="border-destructive/50">
        <CardHeader>
          <CardTitle className="text-destructive">{t("dangerZone")}</CardTitle>
          <CardDescription>{t("dangerZoneDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            variant="destructive"
            onClick={() => void handleDelete()}
            disabled={deleteEvent.isPending}
          >
            <Trash2 className="h-4 w-4" />
            {t("deleteEvent")}
          </Button>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={deleteConfirmOpen}
        onOpenChange={setDeleteConfirmOpen}
        title={t("deleteEvent")}
        description={t("deleteEventConfirm")}
        confirmLabel={t("deleteEvent")}
        destructive
        onConfirm={() => deleteEvent.mutate({ eventId })}
        isLoading={deleteEvent.isPending}
      />
      {scopePrompt.dialog}
    </div>
  );
}
