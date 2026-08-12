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
import { DateTimePicker } from "@/components/ui/date-time-picker";
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
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useAuth } from "@/hooks/useAuth";
import { useCreateCalendarEvent } from "@/hooks/useCalendarEvents";
import { useCalendarsList } from "@/hooks/useCalendars";
import { getItem, setItem } from "@/lib/storage";
import type { DialogProps } from "@/types/dialog";

import {
  datesAreValid,
  endTimeOptionsFor,
  offsetEndTime,
  parseLocalDate,
  reconcileEndTime,
  shiftEndPreservingDuration,
  TIME_OPTIONS,
} from "./eventDateTime";

/** A calendar the user may author events in — write access on the calendar
 * is the event-create gate (like task creation via project write). */
export const isWritableCalendar = (calendar: CalendarSummary): boolean =>
  calendar.my_permission_level === "write" || calendar.my_permission_level === "owner";

const LAST_CALENDAR_KEY = "initiative-last-event-calendar";

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
  const [startDate, setStartDate] = useState("");
  const [startTime, setStartTime] = useState("09:00");
  const [endDate, setEndDate] = useState("");
  const [endTime, setEndTime] = useState("10:00");
  const [allDay, setAllDay] = useState(false);
  const [attendeeIds, setAttendeeIds] = useState<number[]>([]);
  const [recurrence, setRecurrence] = useState<TaskRecurrenceOutput | null>(null);
  const [recurrenceStrategy, setRecurrenceStrategy] =
    useState<TaskListReadRecurrenceStrategy>("fixed");
  const [selectedCalendarId, setSelectedCalendarId] = useState(
    defaultCalendarId ? String(defaultCalendarId) : ""
  );

  // Calendars the current user may author events in (write on the calendar).
  const calendarsQuery = useCalendarsList(
    { page_size: 200, ...(initiativeId ? { initiative_id: initiativeId } : {}) },
    { enabled: open }
  );
  const writableCalendars = useMemo(
    () => (calendarsQuery.data?.items ?? []).filter(isWritableCalendar),
    [calendarsQuery.data]
  );

  const effectiveCalendarId =
    calendarId ?? (selectedCalendarId ? Number(selectedCalendarId) : null);
  const effectiveCalendar = useMemo(
    () =>
      (calendarsQuery.data?.items ?? []).find((calendar) => calendar.id === effectiveCalendarId) ??
      null,
    [calendarsQuery.data, effectiveCalendarId]
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
      if (defaultStartDate) {
        setStartDate(defaultStartDate);
        setEndDate(defaultStartDate);
      }
      if (defaultStartTime) {
        setStartTime(defaultStartTime);
        setEndTime(offsetEndTime(defaultStartTime));
      }
    } else {
      setTitle("");
      setDescription("");
      setLocation("");
      setStartDate("");
      setStartTime("09:00");
      setEndDate("");
      setEndTime("10:00");
      setAllDay(false);
      setAttendeeIds([]);
      setRecurrence(null);
      setRecurrenceStrategy("fixed");
      setSelectedCalendarId(defaultCalendarId ? String(defaultCalendarId) : "");
    }
  }, [open, defaultCalendarId, defaultStartDate, defaultStartTime, user]);

  // Apply a new start date/time, shifting the end so the event keeps its
  // current length (a 90-minute event stays 90 minutes; a multi-day event keeps
  // its span). The end may land on a later day — that's how multi-day timed
  // events are created.
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

  // Guard submit against an end that lands before the start (possible after the
  // user edits the end date/time independently).
  const datesValid = useMemo(
    () => datesAreValid(allDay, startDate, startTime, endDate, endTime),
    [allDay, startDate, endDate, startTime, endTime]
  );

  const createEvent = useCreateCalendarEvent({
    onSuccess: (event) => {
      setItem(`${LAST_CALENDAR_KEY}:${guildId}`, String(event.calendar_id));
      onOpenChange(false);
      onSuccess?.(event);
    },
  });

  const isCreating = createEvent.isPending;
  const canSubmit = title.trim() && datesValid && !!effectiveCalendarId && !isCreating;

  const handleSubmit = () => {
    const trimmedTitle = title.trim();
    if (!trimmedTitle || !datesValid || !effectiveCalendarId) return;

    let startISO: string;
    let endISO: string;
    if (allDay) {
      startISO = new Date(`${startDate}T00:00:00`).toISOString();
      endISO = new Date(`${endDate || startDate}T23:59:59`).toISOString();
    } else {
      startISO = new Date(`${startDate}T${startTime}:00`).toISOString();
      endISO = new Date(`${endDate || startDate}T${endTime}:00`).toISOString();
    }

    createEvent.mutate({
      title: trimmedTitle,
      description: description.trim() || undefined,
      location: location.trim() || undefined,
      start_at: startISO,
      end_at: endISO,
      all_day: allDay,
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

  const referenceDate = startDate ? `${startDate}T${startTime}:00` : undefined;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border bg-card shadow-2xl">
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
                          style={{ backgroundColor: calendar.color ?? "#6366f1" }}
                        />
                        {calendar.name}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="flex items-center gap-3">
            <Switch id="create-event-all-day" checked={allDay} onCheckedChange={setAllDay} />
            <Label htmlFor="create-event-all-day">{t("allDay")}</Label>
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
