import { Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CalendarEventRead,
  CalendarSummary,
  TaskListReadRecurrenceStrategy,
  TaskRecurrenceOutput,
} from "@/api/generated/initiativeAPI.schemas";
import { MemberMultiSelect } from "@/components/members/MemberSearchSelect";
import { TaskRecurrenceSelector } from "@/components/projects/TaskRecurrenceSelector";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useAuth } from "@/hooks/useAuth";
import { useCreateCalendarEvent } from "@/hooks/useCalendarEvents";
import { useCalendar, useCalendarsList } from "@/hooks/useCalendars";
import { hasWriteAccess } from "@/lib/permissions";
import { getItem, setItem } from "@/lib/storage";
import type { DialogProps } from "@/types/dialog";

import { EventDateTimeFields, type EventTiming, useEventTiming } from "./EventDateTimeFields";
import { offsetEndTime } from "./eventDateTime";

/** A calendar the user may author events in — write access on the calendar
 * is the event-create gate (like task creation via project write). */
export const isWritableCalendar = (calendar: CalendarSummary): boolean =>
  hasWriteAccess(calendar.my_permission_level);

const LAST_CALENDAR_KEY = "initiative-last-event-calendar";

const INITIAL_TIMING: EventTiming = {
  allDay: false,
  startDate: "",
  startTime: "09:00",
  endDate: "",
  endTime: "10:00",
};

type CreateEventDialogProps = DialogProps & {
  /** If provided, the calendar is locked and the picker is hidden. */
  calendarId?: number;
  /** If provided, pre-selects this calendar (but the user can change it). */
  defaultCalendarId?: number;
  /** Restrict the picker to this initiative's calendars (initiative tab). */
  initiativeId?: number;
  defaultStartDate?: string;
  defaultStartTime?: string;
  onSuccess?: (event: CalendarEventRead) => void;
};

export const CreateEventDialog = ({
  open,
  onOpenChange,
  calendarId,
  defaultCalendarId,
  initiativeId,
  defaultStartDate,
  defaultStartTime,
  onSuccess,
}: CreateEventDialogProps) => {
  const { t } = useTranslation(["calendars", "common"]);
  const { user } = useAuth();
  const guildId = useActiveGuildId();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [location, setLocation] = useState("");
  const [timing, setTiming] = useState(INITIAL_TIMING);
  const patchTiming = (patch: Partial<EventTiming>) => setTiming((prev) => ({ ...prev, ...patch }));
  const [attendeeIds, setAttendeeIds] = useState<number[]>([]);
  const [recurrence, setRecurrence] = useState<TaskRecurrenceOutput | null>(null);
  const [recurrenceStrategy, setRecurrenceStrategy] =
    useState<TaskListReadRecurrenceStrategy>("fixed");
  const [selectedCalendarId, setSelectedCalendarId] = useState(
    defaultCalendarId ? String(defaultCalendarId) : ""
  );

  // Calendars the current user may author events in (write on the calendar).
  // Locked to one calendar the picker is hidden, so there is no list to fill:
  // that calendar is read on its own instead. A guild calendar's surface shows
  // guild-level content only, and this is the one read on it that would
  // otherwise span the guild's initiatives.
  const calendarsQuery = useCalendarsList(
    { page_size: 200, ...(initiativeId ? { initiative_id: initiativeId } : {}) },
    { enabled: open && calendarId === undefined }
  );
  const writableCalendars = useMemo(
    () => (calendarsQuery.data?.items ?? []).filter(isWritableCalendar),
    [calendarsQuery.data]
  );
  const lockedCalendarQuery = useCalendar(calendarId ?? null, { enabled: open });

  const effectiveCalendarId =
    calendarId ?? (selectedCalendarId ? Number(selectedCalendarId) : null);
  const effectiveCalendar = useMemo(
    () =>
      lockedCalendarQuery.data ??
      (calendarsQuery.data?.items ?? []).find((calendar) => calendar.id === effectiveCalendarId) ??
      null,
    [lockedCalendarQuery.data, calendarsQuery.data, effectiveCalendarId]
  );

  // Default the picker: explicit default > last-used (per guild) > the only
  // writable calendar.
  useEffect(() => {
    if (!open || calendarId !== undefined || selectedCalendarId) return;
    if (defaultCalendarId) {
      setSelectedCalendarId(String(defaultCalendarId));
      return;
    }
    const lastUsed = Number(getItem(`${LAST_CALENDAR_KEY}:${guildId}`) ?? "");
    if (lastUsed && writableCalendars.some((calendar) => calendar.id === lastUsed)) {
      setSelectedCalendarId(String(lastUsed));
      return;
    }
    if (writableCalendars.length === 1) {
      setSelectedCalendarId(String(writableCalendars[0].id));
    }
  }, [open, calendarId, selectedCalendarId, defaultCalendarId, guildId, writableCalendars]);

  useEffect(() => {
    if (open) {
      // The creator attends their own event by default.
      setAttendeeIds(user ? [user.id] : []);
      setTiming((prev) => ({
        ...prev,
        ...(defaultStartDate ? { startDate: defaultStartDate, endDate: defaultStartDate } : {}),
        ...(defaultStartTime
          ? { startTime: defaultStartTime, endTime: offsetEndTime(defaultStartTime) }
          : {}),
      }));
    } else {
      setTitle("");
      setDescription("");
      setLocation("");
      setTiming(INITIAL_TIMING);
      setAttendeeIds([]);
      setRecurrence(null);
      setRecurrenceStrategy("fixed");
      setSelectedCalendarId(defaultCalendarId ? String(defaultCalendarId) : "");
    }
  }, [open, defaultCalendarId, defaultStartDate, defaultStartTime, user]);

  // Null while the end lands before the start (possible after the user edits
  // the end date/time independently), which holds the submit back.
  const range = useEventTiming(timing);

  const createEvent = useCreateCalendarEvent({
    onSuccess: (event) => {
      setItem(`${LAST_CALENDAR_KEY}:${guildId}`, String(event.calendar_id));
      onOpenChange(false);
      onSuccess?.(event);
    },
  });

  const isCreating = createEvent.isPending;
  const canSubmit = title.trim() && !!range && !!effectiveCalendarId && !isCreating;

  const handleSubmit = () => {
    const trimmedTitle = title.trim();
    if (!trimmedTitle || !range || !effectiveCalendarId) return;

    createEvent.mutate({
      title: trimmedTitle,
      description: description.trim() || undefined,
      location: location.trim() || undefined,
      ...range,
      all_day: timing.allDay,
      calendar_id: effectiveCalendarId,
      attendee_ids: attendeeIds.length > 0 ? attendeeIds : undefined,
      recurrence: recurrence
        ? {
            frequency: recurrence.frequency,
            interval: recurrence.interval,
            weekdays: recurrence.weekdays.length ? recurrence.weekdays : undefined,
            monthly_mode: recurrence.monthly_mode ?? undefined,
            day_of_month: recurrence.day_of_month ?? undefined,
            weekday_position: recurrence.weekday_position ?? undefined,
            weekday: recurrence.weekday ?? undefined,
            month: recurrence.month ?? undefined,
            ends: recurrence.ends ?? "never",
            end_after_occurrences: recurrence.end_after_occurrences ?? undefined,
            end_date: recurrence.end_date ?? undefined,
          }
        : undefined,
    });
  };

  const referenceDate = timing.startDate ? `${timing.startDate}T${timing.startTime}:00` : undefined;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] w-full overflow-y-auto rounded-2xl border bg-card shadow-2xl sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("createEvent")}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="create-event-title">{t("eventTitle")}</Label>
            <Input
              id="create-event-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t("titlePlaceholder")}
              onKeyDown={(e) => {
                if (e.key === "Enter" && canSubmit) {
                  e.preventDefault();
                  handleSubmit();
                }
              }}
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="create-event-description">{t("description")}</Label>
            <Textarea
              id="create-event-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t("descriptionPlaceholder")}
              rows={2}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="create-event-location">{t("location")}</Label>
            <Input
              id="create-event-location"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder={t("locationPlaceholder")}
            />
          </div>

          {calendarId === undefined && (
            <div className="space-y-2">
              <Label htmlFor="create-event-calendar">{t("calendar")}</Label>
              <Select
                value={selectedCalendarId}
                onValueChange={(value) => {
                  setSelectedCalendarId(value);
                  // Attendees are initiative members; a new target starts over
                  // with just the creator.
                  setAttendeeIds(user ? [user.id] : []);
                }}
              >
                <SelectTrigger id="create-event-calendar">
                  <SelectValue placeholder={t("selectCalendar")} />
                </SelectTrigger>
                <SelectContent>
                  {writableCalendars.map((calendar) => (
                    <SelectItem key={calendar.id} value={String(calendar.id)}>
                      <span className="inline-flex items-center gap-2">
                        <span
                          className="inline-block h-2.5 w-2.5 rounded-full"
                          style={{ backgroundColor: calendar.color }}
                        />
                        {calendar.name}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <EventDateTimeFields value={timing} onChange={patchTiming} />

          {/* Attendees come from whatever the calendar belongs to — an
              initiative's members, or the whole guild for a guild calendar,
              which belongs to no initiative. Wait until a calendar is chosen. */}
          {effectiveCalendar != null && (
            <div className="space-y-2">
              <Label>{t("attendees")}</Label>
              <MemberMultiSelect
                scope={
                  effectiveCalendar.initiative_id == null
                    ? { type: "guild" }
                    : { type: "initiative", initiativeId: effectiveCalendar.initiative_id }
                }
                selectedIds={attendeeIds}
                selectedUsers={user ? [user] : undefined}
                onChange={setAttendeeIds}
                currentUserId={user?.id}
                placeholder={t("addAttendee")}
                emptyMessage={t("noAttendees")}
              />
            </div>
          )}

          {/* Recurrence */}
          <TaskRecurrenceSelector
            recurrence={recurrence}
            onChange={setRecurrence}
            strategy={recurrenceStrategy}
            onStrategyChange={setRecurrenceStrategy}
            referenceDate={referenceDate}
          />

          {/* No access section: sharing lives on the calendar, not the event. */}
        </div>

        <DialogFooter>
          <Button type="button" onClick={handleSubmit} disabled={!canSubmit}>
            {isCreating ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {t("creating")}
              </>
            ) : (
              t("createEvent")
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
