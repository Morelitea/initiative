import { useEffect, useMemo, useState } from "react";
import { Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useCreateCalendarEvent } from "@/hooks/useCalendarEvents";
import { useInitiativeMembers } from "@/hooks/useInitiatives";
import { TaskRecurrenceSelector } from "@/components/projects/TaskRecurrenceSelector";
import { Badge } from "@/components/ui/badge";
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
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type {
  CalendarEventRead,
  TaskRecurrenceOutput,
  TaskListReadRecurrenceStrategy,
} from "@/api/generated/initiativeAPI.schemas";
import type { DialogProps } from "@/types/dialog";

// Generate half-hour time slots
const TIME_OPTIONS = Array.from({ length: 48 }, (_, i) => {
  const hour = Math.floor(i / 2);
  const minute = i % 2 === 0 ? "00" : "30";
  const hh = String(hour).padStart(2, "0");
  const label = `${hour === 0 ? 12 : hour > 12 ? hour - 12 : hour}:${minute} ${hour < 12 ? "AM" : "PM"}`;
  return { value: `${hh}:${minute}`, label };
});

type CreateEventDialogProps = DialogProps & {
  initiativeId: number;
  defaultStartDate?: string;
  defaultStartTime?: string;
  onSuccess?: (event: CalendarEventRead) => void;
};

export const CreateEventDialog = ({
  open,
  onOpenChange,
  initiativeId,
  defaultStartDate,
  defaultStartTime,
  onSuccess,
}: CreateEventDialogProps) => {
  const { t } = useTranslation(["events", "common"]);

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

  // Fetch initiative members for attendee picker
  const { data: members } = useInitiativeMembers(initiativeId);

  const memberItems = useMemo(() => {
    return (members ?? [])
      .filter((m) => !attendeeIds.includes(m.id))
      .map((m) => ({
        value: String(m.id),
        label: m.full_name || m.email,
      }));
  }, [members, attendeeIds]);

  const attendeeNames = useMemo(() => {
    const map = new Map<number, string>();
    for (const m of members ?? []) {
      map.set(m.id, m.full_name || m.email);
    }
    return map;
  }, [members]);

  useEffect(() => {
    if (open) {
      if (defaultStartDate) {
        setStartDate(defaultStartDate);
        setEndDate(defaultStartDate);
      }
      if (defaultStartTime) {
        setStartTime(defaultStartTime);
        const [h, m] = defaultStartTime.split(":").map(Number);
        const endH = Math.min(h + 1, 23);
        setEndTime(`${String(endH).padStart(2, "0")}:${String(m).padStart(2, "0")}`);
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
    }
  }, [open, defaultStartDate, defaultStartTime]);

  const createEvent = useCreateCalendarEvent({
    onSuccess: (event) => {
      onOpenChange(false);
      onSuccess?.(event);
    },
  });

  const isCreating = createEvent.isPending;
  const canSubmit = title.trim() && startDate && !isCreating;

  const handleSubmit = () => {
    const trimmedTitle = title.trim();
    if (!trimmedTitle || !startDate) return;

    let startISO: string;
    let endISO: string;
    if (allDay) {
      startISO = new Date(`${startDate}T00:00:00`).toISOString();
      endISO = new Date(`${endDate || startDate}T23:59:59`).toISOString();
    } else {
      startISO = new Date(`${startDate}T${startTime}:00`).toISOString();
      endISO = new Date(`${startDate}T${endTime}:00`).toISOString();
    }

    createEvent.mutate({
      title: trimmedTitle,
      description: description.trim() || undefined,
      location: location.trim() || undefined,
      start_at: startISO,
      end_at: endISO,
      all_day: allDay,
      initiative_id: initiativeId,
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
      <DialogContent className="bg-card max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border shadow-2xl">
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

          <div className="flex items-center gap-3">
            <Switch
              id="create-event-all-day"
              checked={allDay}
              onCheckedChange={setAllDay}
            />
            <Label htmlFor="create-event-all-day">{t("allDay")}</Label>
          </div>

          {allDay ? (
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("startDate")}</Label>
                <Input
                  type="date"
                  value={startDate}
                  onChange={(e) => {
                    setStartDate(e.target.value);
                    if (!endDate || e.target.value > endDate) {
                      setEndDate(e.target.value);
                    }
                  }}
                />
              </div>
              <div className="space-y-2">
                <Label>{t("endDate")}</Label>
                <Input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  min={startDate || undefined}
                />
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="space-y-2">
                <Label>{t("startDate")}</Label>
                <Input
                  type="date"
                  value={startDate}
                  onChange={(e) => {
                    setStartDate(e.target.value);
                    setEndDate(e.target.value);
                  }}
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>{t("startDate")}</Label>
                  <Select value={startTime} onValueChange={setStartTime}>
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
                <div className="space-y-2">
                  <Label>{t("endDate")}</Label>
                  <Select value={endTime} onValueChange={setEndTime}>
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
            </div>
          )}

          {/* Attendees */}
          <div className="space-y-2">
            <Label>{t("attendees")}</Label>
            <SearchableCombobox
              items={memberItems}
              value={null}
              onValueChange={(val) => {
                if (val) {
                  setAttendeeIds((prev) => [...prev, Number(val)]);
                }
              }}
              placeholder={t("addAttendee")}
              emptyMessage={t("noAttendees")}
            />
            {attendeeIds.length > 0 && (
              <div className="flex flex-wrap gap-1.5 pt-1">
                {attendeeIds.map((id) => (
                  <Badge key={id} variant="secondary" className="gap-1 pr-1">
                    {attendeeNames.get(id) ?? `User ${id}`}
                    <button
                      type="button"
                      className="hover:bg-muted rounded-full p-0.5"
                      onClick={() => setAttendeeIds((prev) => prev.filter((a) => a !== id))}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </Badge>
                ))}
              </div>
            )}
          </div>

          {/* Recurrence */}
          <TaskRecurrenceSelector
            recurrence={recurrence}
            onChange={setRecurrence}
            strategy={recurrenceStrategy}
            onStrategyChange={setRecurrenceStrategy}
            referenceDate={referenceDate}
          />
        </div>

        <DialogFooter>
          <Button type="button" onClick={handleSubmit} disabled={!canSubmit}>
            {isCreating ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
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
