import { Link } from "@tanstack/react-router";
import { CalendarDays, MapPin, Repeat } from "lucide-react";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import {
  type CalendarEventRead,
  type RSVPStatus,
  SearchEntityType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { utcDateKey } from "@/components/calendar/eventCalendarEntry";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import {
  EventDateTimeFields,
  type EventTiming,
  eventRange,
} from "@/components/initiativeTools/events/EventDateTimeFields";
import { toDateKey, toTimeSlotRounded } from "@/components/initiativeTools/events/eventDateTime";
import { MemberMultiSelect } from "@/components/members/MemberSearchSelect";
import type { OccurrenceScope } from "@/components/recurrence/OccurrenceScopeDialog";
import { RecurrenceEditor } from "@/components/recurrence/RecurrenceEditor";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import {
  eventSaves,
  useEventFieldSave,
  useOccurrenceAction,
  useUpdateEventRSVP,
} from "@/hooks/useCalendarEvents";
import { useCommunityPath } from "@/lib/communityUrl";
import { getHttpStatus } from "@/lib/errorMessage";
import { formatDate, formatDateTime } from "@/lib/formatDate";
import { dateTimeFormat } from "@/lib/intl";
import { toast } from "@/lib/mascotToast";
import {
  allDayReference,
  fromStored,
  type RecurrenceRule,
  rulePayload,
  summarizeStored,
} from "@/lib/recurrence";
import { hour12Option } from "@/lib/timeFormat";
import { eventRoute } from "@/lib/tools";
import { getUserDisplayName } from "@/lib/userDisplay";
import type { TranslateFn } from "@/types/i18n";

import { FieldFrame, useFieldDraft } from "./editing";
import { EVENT_PAGE_KIND } from "./events";
import { PropertiesField, TagsField, TitleField } from "./fieldEditors";
import { useProjectViewEnv } from "./fields";
import type { StoredRegions } from "./itemPage";
import { LAYOUT_PARTS, type Parts, renderNode, type ViewContext } from "./tree";

/** What an event's page shares with its parts, beside the event itself. */
export interface EventPageContext {
  /** The server says the reader cannot change the event. */
  readOnly: boolean;
  /** Why, when it does. */
  readOnlyMessage: string | null;
  initiativeId: number | null;
  /** The date of a repeating event the page was opened at, when it names one. */
  occurrence: string | undefined;
  /** The date a change here is about, by its start in the series. */
  occurrenceStart: string;
  /** When the date shown starts and ends. */
  shownStart: string;
  shownEnd: string;
  askScope: (action: "edit") => Promise<OccurrenceScope | null>;
  /** Takes the page to the event a change answered with: one date of a
   *  repeating event made its own, or the new series from it. */
  onMoved: (moved: CalendarEventRead) => void;
  /** Reporting it, and the menu of what else can be done with it. */
  actions: ReactNode;
}

const PageContext = createContext<EventPageContext | null>(null);

const useEventPage = (): EventPageContext => {
  const page = useContext(PageContext);
  if (!page) throw new Error("An event page part is drawn outside its page");
  return page;
};

type EditorProps = { event: CalendarEventRead; label: string };

/** A field's save, for the page it is on. */
const useSave = (event: CalendarEventRead, label: string) =>
  useEventFieldSave(event, label, useEventPage());

const sameJson = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

const RSVP_LABEL_KEYS: Record<
  string,
  "rsvpPending" | "rsvpAccepted" | "rsvpDeclined" | "rsvpTentative"
> = {
  pending: "rsvpPending",
  accepted: "rsvpAccepted",
  declined: "rsvpDeclined",
  tentative: "rsvpTentative",
};

const rsvpBadgeVariant = (
  status: RSVPStatus
): "default" | "secondary" | "destructive" | "outline" =>
  status === "accepted"
    ? "default"
    : status === "declined"
      ? "destructive"
      : status === "tentative"
        ? "outline"
        : "secondary";

const DAY = { weekday: "long", year: "numeric", month: "long", day: "numeric" } as const;

const formatDay = (value: string, allDay: boolean) =>
  // An all-day event's date is its UTC date, the same for every viewer.
  dateTimeFormat(undefined, allDay ? { ...DAY, timeZone: "UTC" } : DAY).format(new Date(value));

const formatTime = (value: string) =>
  dateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    hour12: hour12Option(),
  }).format(new Date(value));

/** An event's dates as a reader reads them: one day with its times, or from
 *  one moment to another. */
const formatRange = (start: string, end: string, allDay: boolean): string => {
  if (allDay) {
    const [first, last] = [formatDay(start, true), formatDay(end, true)];
    return first === last ? first : `${first} - ${last}`;
  }
  const [from, to] = [new Date(start), new Date(end)];
  const sameDay = from.toDateString() === to.toDateString();
  return sameDay
    ? `${formatDay(start, false)}, ${formatTime(start)} - ${formatTime(end)}`
    : `${formatDay(start, false)}, ${formatTime(start)} - ${formatDay(end, false)}, ${formatTime(end)}`;
};

/** The event's title, which is the page's heading. */
const TitleEditor = ({ event, label }: EditorProps) => {
  const { t } = useTranslation("calendars");
  const { readOnly } = useEventPage();
  return (
    <TitleField
      id="event-title"
      label={label}
      value={event.title}
      save={useSave(event, label)}
      readOnly={readOnly}
      placeholder={t("eventPage.titlePlaceholder")}
    />
  );
};

/**
 * The description, saved when its field is left. The save names the
 * description it was written over, and one written over a description that
 * has since changed is refused, so the reader sees the other version and
 * chooses.
 */
const DescriptionEditor = ({ event, label }: EditorProps) => {
  const { t } = useTranslation(["calendars", "common"]);
  const { readOnly } = useEventPage();
  const save = useSave(event, label);
  const current = event.description ?? "";
  // What was last sent, which a refused save offers to send again.
  const sent = useRef("");
  const write = (text: string, base: string | null) => {
    sent.current = text;
    const description = text.trim() || null;
    return save.save({ patch: { description, description_base: base }, shows: { description } });
  };
  const draft = useFieldDraft(current, (text) => write(text, event.description ?? null));
  const conflict = getHttpStatus(save.error) === 409;
  if (readOnly) {
    return current ? (
      <p className="whitespace-pre-wrap text-sm">{current}</p>
    ) : (
      <p className="text-muted-foreground text-sm italic">{t("eventPage.noDescription")}</p>
    );
  }
  return (
    <FieldFrame
      label={label}
      htmlFor="event-description"
      save={conflict ? { ...save, state: "idle" } : save}
      changed={draft.changed}
      keys={draft.keys}
    >
      <Textarea
        id="event-description"
        value={draft.value}
        onChange={(change) => draft.change(change.target.value)}
        placeholder={t("descriptionPlaceholder")}
        rows={3}
      />
      {conflict ? (
        <div
          role="alert"
          className="space-y-2 rounded-md border border-warning/40 bg-warning/5 px-3 py-2"
        >
          <p className="text-sm">{t("common:fieldSave.changed")}</p>
          <p className="whitespace-pre-wrap rounded-md border bg-background px-3 py-2 text-sm">
            {current}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              onClick={() => void write(sent.current, event.description ?? null)}
            >
              {t("common:fieldSave.overwrite")}
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={save.reset}>
              {t("common:fieldSave.discard")}
            </Button>
          </div>
        </div>
      ) : null}
    </FieldFrame>
  );
};

const LocationEditor = ({ event, label }: EditorProps) => {
  const { t } = useTranslation("calendars");
  const { readOnly } = useEventPage();
  const save = useSave(event, label);
  const saved = event.location ?? "";
  const edit = (text: string) => {
    const location = text.trim() || null;
    return { patch: { location }, shows: { location } };
  };
  const draft = useFieldDraft(saved, (text) =>
    save.save(edit(text), text.trim() || !saved ? undefined : edit(saved))
  );
  if (readOnly) {
    return saved ? (
      <div className="flex items-start gap-3">
        <MapPin className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
        <p className="text-sm">{saved}</p>
      </div>
    ) : null;
  }
  return (
    <FieldFrame
      label={label}
      htmlFor="event-location"
      save={save}
      changed={draft.changed}
      keys={draft.keys}
    >
      <Input
        id="event-location"
        value={draft.value}
        onChange={(change) => draft.change(change.target.value)}
        placeholder={t("locationPlaceholder")}
      />
    </FieldFrame>
  );
};

/** When the date shown starts and ends, as the pickers hold it. */
const timingOf = (start: string, end: string, allDay: boolean): EventTiming => {
  const [from, to] = [new Date(start), new Date(end)];
  return {
    allDay,
    // An all-day event's dates are UTC dates.
    startDate: allDay ? utcDateKey(from.toISOString()) : toDateKey(from),
    startTime: toTimeSlotRounded(from),
    endDate: allDay ? utcDateKey(to.toISOString()) : toDateKey(to),
    endTime: toTimeSlotRounded(to),
  };
};

/** The start, the end and whether it lasts all day, saved as one. For one
 *  date of a repeating event they are that date's, which the change asks
 *  about. */
const DatesEditor = ({ event }: { event: CalendarEventRead }) => {
  const { t } = useTranslation(["calendars", "common"]);
  const { readOnly, shownStart, shownEnd } = useEventPage();
  const label = t("eventPage.when");
  const save = useSave(event, label);
  const repeating = Boolean(event.recurrence) || event.series_id != null;
  const draft = useFieldDraft(
    timingOf(shownStart, shownEnd, event.all_day),
    (timing) => {
      const range = eventRange(timing);
      if (!range) return Promise.resolve(false);
      const patch = { ...range, all_day: timing.allDay };
      // A series' own times are not the date's, so nothing shows until it answers.
      return save.save({ patch, shows: repeating ? {} : patch });
    },
    sameJson,
    (timing) => eventRange(timing) !== null
  );
  if (readOnly) {
    return (
      <div className="flex items-start gap-3">
        <CalendarDays className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-medium">{formatRange(shownStart, shownEnd, event.all_day)}</p>
          {event.all_day ? <Badge variant="secondary">{t("common:calendar.allDay")}</Badge> : null}
        </div>
      </div>
    );
  }
  return (
    <FieldFrame label={label} save={save} changed={draft.changed} keys={draft.keys}>
      <EventDateTimeFields
        value={draft.value}
        onChange={(patch) => draft.edit({ ...draft.value, ...patch })}
      />
    </FieldFrame>
  );
};

/**
 * How the event repeats, and the dates it skips or adds. One date with a row
 * of its own repeats with its series, which is where that changes; opened at
 * one date of a series, it can be made a row of its own.
 */
const RepeatEditor = ({ event, label }: EditorProps) => {
  const { t } = useTranslation(["calendars", "common"]);
  const { readOnly, occurrence, occurrenceStart, onMoved, initiativeId } = useEventPage();
  const gp = useCommunityPath();
  const save = useSave(event, label);
  const saved: RecurrenceRule | "custom" | null = fromStored(
    event.recurrence,
    event.start_at,
    event.recurrence_shift,
    event.all_day
  );
  const draft = useFieldDraft(
    saved,
    (rule) =>
      rule === "custom"
        ? Promise.resolve(false)
        : save.save({ patch: rulePayload(rule, { allDay: event.all_day }), shows: {} }),
    sameJson
  );
  const openAlone = useOccurrenceAction(event.id, "open", { onSuccess: onMoved });
  const restoreDate = useOccurrenceAction(event.id, "restore", {
    onSuccess: () => toast.success(t("occurrence.restored")),
  });
  const [extraDate, setExtraDate] = useState("");
  const addDate = useOccurrenceAction(event.id, "add", {
    onSuccess: () => {
      toast.success(t("occurrence.added"));
      setExtraDate("");
    },
  });

  if (event.series_id != null) {
    return (
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
    );
  }
  if (readOnly) {
    return event.recurrence ? (
      <div className="flex items-start gap-3">
        <Repeat className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
        <p className="text-sm">
          {summarizeStored(
            event.recurrence,
            event.start_at,
            { shift: event.recurrence_shift, allDay: event.all_day },
            t as TranslateFn
          )}
        </p>
      </div>
    ) : null;
  }
  return (
    <FieldFrame label={label} hideLabel save={save} changed={draft.changed} keys={draft.keys}>
      <RecurrenceEditor
        kind="event"
        value={draft.value}
        onChange={draft.edit}
        referenceDate={event.all_day ? allDayReference(event.start_at) : event.start_at}
        allDay={event.all_day}
        stored={event.recurrence ? { rule: event.recurrence, shift: event.recurrence_shift } : null}
      />
      {event.recurrence && occurrence ? (
        <Button
          type="button"
          variant="link"
          className="h-auto p-0"
          onClick={() => openAlone.mutate(occurrenceStart)}
          disabled={openAlone.isPending}
        >
          {t("occurrence.openAlone")}
        </Button>
      ) : null}
      {event.recurrence
        ? (
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
                          type="button"
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
          )
        : null}
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
            type="button"
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
    </FieldFrame>
  );
};

const sameIds = (a: number[], b: number[]) => sameJson([...a].sort(), [...b].sort());

/** Who is coming, each with their answer; who is asked, saved as they are
 *  picked; and whether anyone who can see it may answer. */
const AttendeesEditor = ({ event }: { event: CalendarEventRead }) => {
  const { t } = useTranslation(["calendars", "common"]);
  const { readOnly } = useEventPage();
  const label = `${t("attendees")} (${event.attendees.length})`;
  const save = useSave(event, t("attendees"));
  const openSave = useSave(event, t("rsvpOpen"));
  const saved = event.attendees.map((attendee) => attendee.user_id);
  const draft = useFieldDraft(
    saved,
    (ids) => save.save({ patch: { attendee_ids: ids }, shows: {} }),
    sameIds
  );
  const users = useMemo(
    () => event.attendees.flatMap((attendee) => (attendee.user ? [attendee.user] : [])),
    [event.attendees]
  );
  return (
    <FieldFrame label={label} save={save} changed={draft.changed} keys={draft.keys}>
      {readOnly ? null : (
        <MemberMultiSelect
          scope={{ type: "canOpen", tool: Tool.calendar, id: event.calendar_id }}
          selectedIds={draft.value}
          selectedUsers={users}
          onChange={draft.edit}
          placeholder={t("addAttendee")}
          emptyMessage={t("noAttendees")}
        />
      )}
      {event.attendees.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("noAttendees")}</p>
      ) : (
        <ul className="space-y-2">
          {event.attendees.map((attendee) => (
            <li
              key={attendee.user_id}
              className="flex items-center justify-between rounded-md border px-3 py-2"
            >
              <span className="font-medium text-sm">
                {getUserDisplayName(attendee.user ?? { id: attendee.user_id })}
              </span>
              <Badge variant={rsvpBadgeVariant(attendee.rsvp_status)}>
                {t(RSVP_LABEL_KEYS[attendee.rsvp_status] ?? "rsvpPending")}
              </Badge>
            </li>
          ))}
        </ul>
      )}
      {readOnly ? null : (
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <Label htmlFor="event-rsvp-open" className="text-sm">
              {t("rsvpOpen")}
            </Label>
            <p className="text-muted-foreground text-xs">
              {event.series_id != null ? t("occurrence.followsSeries") : t("rsvpOpenHint")}
            </p>
          </div>
          <Switch
            id="event-rsvp-open"
            checked={event.rsvp_open}
            // One date with a row of its own answers as its series is set.
            disabled={event.series_id != null || openSave.state === "saving"}
            onCheckedChange={(next) =>
              void openSave.save({ patch: { rsvp_open: next }, shows: { rsvp_open: next } })
            }
            className="mt-0.5 shrink-0"
          />
        </div>
      )}
    </FieldFrame>
  );
};

/** The reader's own answer, where they are asked. A series' is for the date
 *  shown. */
const MyAnswer = ({ event }: { event: CalendarEventRead }) => {
  const { t } = useTranslation("calendars");
  const { occurrenceStart } = useEventPage();
  const { user } = useAuth();
  const answer = useUpdateEventRSVP(event.id, {
    onSuccess: () => toast.success(t("rsvpUpdated")),
  });
  const mine = event.attendees.find((attendee) => attendee.user_id === user?.id);
  if (!mine) return null;
  return (
    <section className="space-y-2 rounded-lg border bg-card p-4 text-card-foreground shadow-sm">
      <Label htmlFor="event-rsvp">{t("rsvp")}</Label>
      <Select
        // Pending is no answer yet, so it shows as the placeholder rather
        // than as a choice.
        value={mine.rsvp_status === "pending" ? "" : mine.rsvp_status}
        onValueChange={(status) =>
          answer.mutate({
            rsvp_status: status as RSVPStatus,
            ...(event.recurrence ? { occurrence: occurrenceStart } : {}),
          })
        }
        disabled={answer.isPending}
      >
        <SelectTrigger id="event-rsvp" className="w-[140px]">
          <SelectValue placeholder={t("rsvpPending")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="accepted">{t("rsvpAccepted")}</SelectItem>
          <SelectItem value="tentative">{t("rsvpTentative")}</SelectItem>
          <SelectItem value="declined">{t("rsvpDeclined")}</SelectItem>
        </SelectContent>
      </Select>
    </section>
  );
};

const TagsEditor = ({ event, label }: EditorProps) => {
  const { t } = useTranslation("calendars");
  const { readOnly } = useEventPage();
  const save = useSave(event, label);
  // A reader sees the tags it has, and none where it has none.
  if (readOnly && event.tags.length === 0) return null;
  return (
    <TagsField
      label={label}
      tags={event.tags}
      save={save}
      readOnly={readOnly}
      placeholder={t("eventPage.tagsPlaceholder")}
    />
  );
};

/** Its custom properties, defined per initiative: an event on a
 *  community-level calendar has none to offer. */
const PropertiesEditor = ({ event }: { event: CalendarEventRead }) => {
  const { readOnly, occurrence } = useEventPage();
  if (event.initiative_id === null) return null;
  if (readOnly && event.properties.length === 0) return null;
  return (
    <PropertiesField
      kind={eventSaves(occurrence)}
      id={event.id}
      properties={event.properties}
      readOnly={readOnly}
      initiativeId={event.initiative_id}
      canOpen={{ tool: Tool.calendar, id: event.calendar_id }}
    />
  );
};

/** Each field's label key. */
const FIELD_LABELS = {
  title: "eventTitle",
  description: "eventPage.description",
  location: "location",
  recurrence: "repeat",
  attendees: "attendees",
  tags: "common:toolSettings.tags",
} as const;

/** Each field's editor on the event's page, by its id. */
const FIELD_EDITORS: Record<keyof typeof FIELD_LABELS, (props: EditorProps) => ReactNode> = {
  title: TitleEditor,
  description: DescriptionEditor,
  location: LocationEditor,
  recurrence: RepeatEditor,
  attendees: AttendeesEditor,
  tags: TagsEditor,
};

/** One field of the event, by its id, labelled in the event's own words. */
const EventField = ({ id, event }: { id: string; event: CalendarEventRead }) => {
  const { t } = useTranslation(["calendars", "common"]);
  if (!Object.hasOwn(FIELD_EDITORS, id)) return null;
  const Editor = FIELD_EDITORS[id as keyof typeof FIELD_EDITORS];
  return <Editor event={event} label={t(FIELD_LABELS[id as keyof typeof FIELD_LABELS])} />;
};

const Notice = () => {
  const { readOnlyMessage } = useEventPage();
  return readOnlyMessage ? (
    <p className="rounded-md border border-border bg-muted/50 px-3 py-2 text-muted-foreground text-sm">
      {readOnlyMessage}
    </p>
  ) : null;
};

const Actions = () => <>{useEventPage().actions}</>;

const Relations = ({ event }: { event: CalendarEventRead }) => (
  <ToolRelationsPanel
    tool={Tool.calendar}
    entity={event}
    target={{ type: SearchEntityType.calendar_event, id: event.id }}
    canEdit={!useEventPage().readOnly}
    entityTitle={event.title}
  />
);

/** The parts an event's page is drawn from. */
const EVENT_PAGE_PARTS: Parts<CalendarEventRead> = {
  ...LAYOUT_PARTS,
  field: (node, event) => <EventField id={String(node.props?.field)} event={event} />,
  dates: (_node, event) => <DatesEditor event={event} />,
  rsvp: (_node, event) => <MyAnswer event={event} />,
  properties: (_node, event) => <PropertiesEditor event={event} />,
  relations: (_node, event) => <Relations event={event} />,
  notice: () => <Notice />,
  actions: () => <Actions />,
};

// An event's page draws no task, so nothing asks it for a task's address.
const NO_TASK = () => "";

/** An event's page, drawn from its initiative's layout, or as shipped. */
export const EventPageView = ({
  event,
  page,
  layout,
}: {
  event: CalendarEventRead;
  page: EventPageContext;
  layout?: StoredRegions | null;
}) => {
  const { t } = useTranslation("calendars");
  const communityId = useActiveCommunityId();
  const env = useProjectViewEnv(useCallback(NO_TASK, []));
  const view = useMemo<ViewContext>(() => ({ fields: new Map(), variant: "page", env }), [env]);
  const tree = useMemo(() => EVENT_PAGE_KIND.tree(layout, t("eventPage.moreFields")), [layout, t]);
  return (
    // Another event's page starts afresh, with none of this one's drafts.
    <PageContext.Provider key={`${communityId}:${event.id}`} value={page}>
      {renderNode(tree, event, view, EVENT_PAGE_PARTS)}
    </PageContext.Provider>
  );
};
