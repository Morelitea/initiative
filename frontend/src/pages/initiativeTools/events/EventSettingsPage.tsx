import { Link, useParams, useRouter } from "@tanstack/react-router";
import { Loader2, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  PropertyDefinitionRead,
  PropertySummary,
  TagSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  datesAreValid,
  endTimeOptionsFor,
  parseLocalDate,
  reconcileEndTime,
  shiftEndPreservingDuration,
  TIME_OPTIONS,
  toDateKey,
  toTimeSlotRounded,
} from "@/components/initiativeTools/events/eventDateTime";
import { MemberMultiSelect } from "@/components/members/MemberSearchSelect";
import { AddPropertyButton, PropertyList } from "@/components/properties";
import { TagPicker } from "@/components/tags";
import { ToolBreadcrumb } from "@/components/tools/ToolBreadcrumb";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  useCalendarEvent,
  useDeleteCalendarEvent,
  useSetEventAttendees,
  useSetEventTags,
  useUpdateCalendarEvent,
} from "@/hooks/useCalendarEvents";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { toast } from "@/lib/chesterToast";
import { useGuildPath } from "@/lib/guildUrl";
import { eventRoute, toolDetailRoute, toolListRoute } from "@/lib/tools";

export function EventSettingsPage() {
  const { t } = useTranslation(["calendars", "common", "access"]);
  const router = useRouter();
  const gp = useGuildPath();
  const { eventId: eventIdParam, calendarId: calendarIdParam } = useParams({ strict: false }) as {
    eventId?: string;
    calendarId?: string;
  };
  const eventId = Number(eventIdParam);
  const calendarId = calendarIdParam ? Number(calendarIdParam) : null;

  const { data: event, isLoading } = useCalendarEvent(Number.isFinite(eventId) ? eventId : null);
  // The path supplies the initiative while this loads; the event is the
  // authority once it arrives, and null is a guild-level calendar's address.
  const initiativeId = useCanonicalInitiativeId(event?.initiative_id);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [location, setLocation] = useState("");
  const [startDate, setStartDate] = useState("");
  const [startTime, setStartTime] = useState("09:00");
  const [endDate, setEndDate] = useState("");
  const [endTime, setEndTime] = useState("10:00");
  const [allDay, setAllDay] = useState(false);
  const [tags, setTags] = useState<TagSummary[]>([]);
  const [attendeeIds, setAttendeeIds] = useState<number[]>([]);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  // Custom properties — staging pattern: newly-attached definitions land in
  // ``pendingProperties`` as stub summaries so they show up immediately in
  // the PropertyList. The list's debounced save handles persistence.
  const [pendingProperties, setPendingProperties] = useState<PropertyDefinitionRead[]>([]);

  // Attendee candidates come from whatever the event's calendar belongs to
  // (MemberMultiSelect below): every member of its initiative, or every member
  // of the guild when the calendar belongs to no initiative. Event DAC (the
  // ShareControl below) is a separate concern tracked in #948. The current
  // attendees carry their own user summaries, so the chips render immediately.
  const attendeeUsers = useMemo(
    () => (event?.attendees ?? []).flatMap((a) => (a.user ? [a.user] : [])),
    [event?.attendees]
  );

  // Merge server-side property values with freshly-attached (pending) defs —
  // mirrors the DocumentDetailPage / TaskEditPage pattern. Pending defs are
  // rendered as stubs so the input shows immediately; the PropertyList's
  // debounced PUT persists them (even with null values so attached-empty
  // rows survive a refresh).
  const serverProperties: PropertySummary[] = useMemo(
    () => event?.property_values ?? [],
    [event?.property_values]
  );
  const serverPropertyIds = useMemo(
    () => new Set(serverProperties.map((p) => p.property_id)),
    [serverProperties]
  );
  const combinedProperties = useMemo<PropertySummary[]>(() => {
    const stubs: PropertySummary[] = pendingProperties
      .filter((def) => !serverPropertyIds.has(def.id))
      .map((def) => ({
        property_id: def.id,
        name: def.name,
        type: def.type,
        options: def.options ?? null,
        value: null,
      }));
    return [...serverProperties, ...stubs];
  }, [serverProperties, pendingProperties, serverPropertyIds]);
  const combinedPropertyIds = useMemo(
    () => combinedProperties.map((p) => p.property_id),
    [combinedProperties]
  );

  // Drop pending stubs once the server snapshot confirms they exist.
  useEffect(() => {
    setPendingProperties((prev) => {
      if (prev.length === 0) return prev;
      const filtered = prev.filter((def) => !serverPropertyIds.has(def.id));
      return filtered.length === prev.length ? prev : filtered;
    });
  }, [serverPropertyIds]);

  const handleAddProperty = (definition: PropertyDefinitionRead) => {
    setPendingProperties((prev) =>
      prev.some((p) => p.id === definition.id) ? prev : [...prev, definition]
    );
  };

  useEffect(() => {
    if (event) {
      setTitle(event.title);
      setDescription(event.description ?? "");
      setLocation(event.location ?? "");
      const start = new Date(event.start_at);
      const end = new Date(event.end_at);
      setStartDate(toDateKey(start));
      setStartTime(toTimeSlotRounded(start));
      setEndDate(toDateKey(end));
      setEndTime(toTimeSlotRounded(end));
      setAllDay(event.all_day);
      setTags(event.tags ?? []);
      setAttendeeIds(event.attendees.map((a) => a.user_id));
    }
  }, [event]);

  // Apply a new start date/time, shifting the end to keep the event's length
  // (mirrors the create dialog; multi-day spans are preserved).
  const applyStart = (nextDate: string, nextTime: string) => {
    setStartDate(nextDate);
    setStartTime(nextTime);
    const shifted = shiftEndPreservingDuration(
      startDate,
      startTime,
      endDate,
      endTime,
      nextDate,
      nextTime
    );
    if (shifted) {
      setEndDate(shifted.endDate);
      setEndTime(shifted.endTime);
    }
  };

  const endTimeOptions = useMemo(
    () => endTimeOptionsFor(startDate, endDate, startTime),
    [startDate, endDate, startTime]
  );

  const datesValid = useMemo(
    () => datesAreValid(allDay, startDate, startTime, endDate, endTime),
    [allDay, startDate, endDate, startTime, endTime]
  );

  const updateEvent = useUpdateCalendarEvent(eventId, {
    onSuccess: () => toast.success(t("detailsUpdated")),
  });

  const setAttendees = useSetEventAttendees(eventId, {
    onSuccess: () => toast.success(t("detailsUpdated")),
  });

  const setEventTags = useSetEventTags(eventId);

  // Tags persist immediately on change (like tasks/documents), no Save button.
  // Optimistically update, then roll back to the prior selection if the save
  // fails (the hook surfaces an error toast on its own).
  const handleTagsChange = (newTags: TagSummary[]) => {
    const previous = tags;
    setTags(newTags);
    setEventTags.mutate(
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

  const handleSave = () => {
    if (!datesValid) return;
    const startValue = allDay ? `${startDate}T00:00:00` : `${startDate}T${startTime}:00`;
    const endValue = allDay
      ? `${endDate || startDate}T23:59:59`
      : `${endDate || startDate}T${endTime}:00`;

    updateEvent.mutate({
      title: title.trim() || undefined,
      description: description.trim() || undefined,
      location: location.trim() || undefined,
      start_at: new Date(startValue).toISOString(),
      end_at: new Date(endValue).toISOString(),
      all_day: allDay,
    });
  };

  const handleSaveAttendees = () => {
    setAttendees.mutate(attendeeIds);
  };

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 p-8 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("loadingEvent")}
      </div>
    );
  }

  if (!event) {
    return (
      <div className="p-8 text-center">
        <p className="text-muted-foreground">{t("notFound")}</p>
        <Button variant="link" asChild className="mt-2">
          <Link to={gp(toolListRoute(Tool.calendar, initiativeId))}>{t("backToEvents")}</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <ToolBreadcrumb
        tool={Tool.calendar}
        initiativeId={initiativeId}
        trail={[
          { label: event.title, to: eventRoute(initiativeId, event.calendar_id, eventId) },
          { label: t("common:toolSettings.title") },
        ]}
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

          <div className="flex items-center gap-3">
            <Switch id="event-all-day" checked={allDay} onCheckedChange={setAllDay} />
            <Label htmlFor="event-all-day">{t("allDay")}</Label>
          </div>

          {allDay ? (
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("startDate")}</Label>
                <DateTimePicker
                  value={startDate}
                  includeTime={false}
                  onChange={(next) => {
                    setStartDate(next);
                    if (!endDate || next > endDate) {
                      setEndDate(next);
                    }
                  }}
                />
              </div>
              <div className="space-y-2">
                <Label>{t("endDate")}</Label>
                <DateTimePicker
                  value={endDate}
                  includeTime={false}
                  onChange={setEndDate}
                  calendarProps={(() => {
                    const min = parseLocalDate(startDate);
                    return min ? { disabled: { before: min } } : undefined;
                  })()}
                />
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>{t("startDate")}</Label>
                  <DateTimePicker
                    value={startDate}
                    includeTime={false}
                    onChange={(next) => applyStart(next, startTime)}
                  />
                </div>
                <div className="space-y-2">
                  <Label>{t("startTime")}</Label>
                  <Select value={startTime} onValueChange={(value) => applyStart(startDate, value)}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="max-h-60">
                      {TIME_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>{t("endDate")}</Label>
                  <DateTimePicker
                    value={endDate}
                    includeTime={false}
                    onChange={(next) => {
                      setEndDate(next);
                      setEndTime(reconcileEndTime(startDate, startTime, next, endTime));
                    }}
                    calendarProps={(() => {
                      const min = parseLocalDate(startDate);
                      return min ? { disabled: { before: min } } : undefined;
                    })()}
                  />
                </div>
                <div className="space-y-2">
                  <Label>{t("endTime")}</Label>
                  <Select value={endTime} onValueChange={setEndTime}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="max-h-60">
                      {endTimeOptions.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </div>
          )}

          <Button onClick={handleSave} disabled={updateEvent.isPending || !datesValid}>
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
          <CardTitle>{t("attendees")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <MemberMultiSelect
            scope={
              event != null && event.initiative_id == null
                ? { type: "guild" }
                : { type: "initiative", initiativeId: event?.initiative_id ?? null }
            }
            selectedIds={attendeeIds}
            selectedUsers={attendeeUsers}
            onChange={setAttendeeIds}
            placeholder={t("addAttendee")}
            emptyMessage={t("noAttendees")}
          />

          <Button onClick={handleSaveAttendees} disabled={setAttendees.isPending}>
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
          guild-level calendar has none to offer. */}
      {event.initiative_id !== null && (
        <Card>
          <CardHeader>
            <CardTitle>{t("properties")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <PropertyList
              entityKind="event"
              entityId={eventId}
              properties={combinedProperties}
              initiativeId={event.initiative_id}
            />
            <AddPropertyButton
              initiativeId={event.initiative_id}
              currentPropertyIds={combinedPropertyIds}
              onAdd={handleAddProperty}
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
            onClick={() => setDeleteConfirmOpen(true)}
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
        onConfirm={() => deleteEvent.mutate(eventId)}
        isLoading={deleteEvent.isPending}
      />
    </div>
  );
}
