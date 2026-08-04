import { Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CalendarEventRead,
  ResourceGrantSchema,
  TaskListReadRecurrenceStrategy,
  TaskRecurrenceOutput,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { CreateAccessSection } from "@/components/access/CreateAccessSection";
import { DEFAULT_GRANTS } from "@/components/access/grants";
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
import { useAuth } from "@/hooks/useAuth";
import { useCreateCalendarEvent } from "@/hooks/useCalendarEvents";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
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

type CreateEventDialogProps = DialogProps & {
  /** If provided, the initiative is locked and the picker is hidden. */
  initiativeId?: number;
  /** If provided, pre-selects this initiative (but the user can change it). */
  defaultInitiativeId?: number;
  defaultStartDate?: string;
  defaultStartTime?: string;
  onSuccess?: (event: CalendarEventRead) => void;
};

export const CreateEventDialog = ({
  open,
  onOpenChange,
  initiativeId,
  defaultInitiativeId,
  defaultStartDate,
  defaultStartTime,
  onSuccess,
}: CreateEventDialogProps) => {
  const { t } = useTranslation(["calendarEvents", "common"]);
  const { user } = useAuth();

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
  const [grants, setGrants] = useState<ResourceGrantSchema[]>([...DEFAULT_GRANTS]);
  const [selectedInitiativeId, setSelectedInitiativeId] = useState(
    defaultInitiativeId ? String(defaultInitiativeId) : ""
  );

  // Initiatives the current user may create events in — backs the picker
  // shown when no initiative is locked (the "All" calendar view).
  const { creatableInitiatives } = useToolCreateAccess(Tool.calendar_event, { enabled: open });

  const effectiveInitiativeId =
    initiativeId ?? (selectedInitiativeId ? Number(selectedInitiativeId) : null);

  // Attendee candidates come from the initiative-scoped member typeahead
  // (MemberMultiSelect below) — every initiative member may attend. Event DAC
  // (the access section below) is a separate concern tracked in #948.

  useEffect(() => {
    if (open) {
      // The creator attends their own event by default.
      setAttendeeIds(user ? [user.id] : []);
      if (defaultInitiativeId) {
        setSelectedInitiativeId(String(defaultInitiativeId));
      }
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
      setGrants([...DEFAULT_GRANTS]);
      setSelectedInitiativeId(defaultInitiativeId ? String(defaultInitiativeId) : "");
    }
  }, [open, defaultInitiativeId, defaultStartDate, defaultStartTime, user]);

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
      onOpenChange(false);
      onSuccess?.(event);
    },
  });

  const isCreating = createEvent.isPending;
  const canSubmit = title.trim() && datesValid && !!effectiveInitiativeId && !isCreating;

  const handleSubmit = () => {
    const trimmedTitle = title.trim();
    if (!trimmedTitle || !datesValid || !effectiveInitiativeId) return;

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
      initiative_id: effectiveInitiativeId,
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
      grants,
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

          {initiativeId === undefined && (
            <div className="space-y-2">
              <Label htmlFor="create-event-initiative">{t("initiative")}</Label>
              <Select
                value={selectedInitiativeId}
                onValueChange={(value) => {
                  setSelectedInitiativeId(value);
                  // Attendees are initiative members; a new target starts over
                  // with just the creator.
                  setAttendeeIds(user ? [user.id] : []);
                }}
              >
                <SelectTrigger id="create-event-initiative">
                  <SelectValue placeholder={t("selectInitiative")} />
                </SelectTrigger>
                <SelectContent>
                  {creatableInitiatives.map((initiative) => (
                    <SelectItem key={initiative.id} value={String(initiative.id)}>
                      {initiative.name}
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

          {/* Attendees — scoped to the target initiative's members, so wait
              until one is chosen. */}
          {effectiveInitiativeId != null && (
            <div className="space-y-2">
              <Label>{t("attendees")}</Label>
              <MemberMultiSelect
                scope={{ type: "initiative", initiativeId: effectiveInitiativeId }}
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

          <CreateAccessSection
            initiativeId={effectiveInitiativeId}
            grants={grants}
            onChange={setGrants}
          />
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
