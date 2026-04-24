import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import {
  CalendarDays,
  Loader2,
  MapPin,
  SearchX,
  Settings,
  ShieldAlert,
  Trash2,
  Users,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  useCalendarEvent,
  useDeleteCalendarEvent,
  useUpdateEventRSVP,
} from "@/hooks/useCalendarEvents";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useAuth } from "@/hooks/useAuth";
import { useGuildPath } from "@/lib/guildUrl";
import { getHttpStatus } from "@/lib/errorMessage";
import { StatusMessage } from "@/components/StatusMessage";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PropertyValueCell } from "@/components/properties/PropertyValueCell";
import { iconForPropertyType } from "@/components/properties/propertyTypeIcons";
import type { RSVPStatus } from "@/api/generated/initiativeAPI.schemas";

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
    return date.toLocaleDateString(undefined, {
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  }

  return date.toLocaleString(undefined, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
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
    });
    const endTime = end.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
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
  const { t } = useTranslation(["events", "common"]);
  const { eventId } = useParams({ strict: false }) as { eventId: string };
  const parsedId = Number(eventId);
  const navigate = useNavigate();
  const gp = useGuildPath();
  const { user } = useAuth();

  const eventQuery = useCalendarEvent(Number.isFinite(parsedId) ? parsedId : null);
  const event = eventQuery.data;

  // Get initiative name for breadcrumb
  const initiativesQuery = useInitiatives();
  const initiativeName = useMemo(() => {
    if (!event) return null;
    const initiative = initiativesQuery.data?.find((i) => i.id === event.initiative_id);
    return initiative?.name ?? null;
  }, [event, initiativesQuery.data]);

  // Delete event
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const deleteEvent = useDeleteCalendarEvent({
    onSuccess: () => {
      toast.success(t("eventDeleted"));
      void navigate({ to: gp("/events") });
    },
  });

  // RSVP
  const updateRSVP = useUpdateEventRSVP(parsedId, {
    onSuccess: () => {
      toast.success(t("rsvpUpdated"));
    },
  });

  const isOwner = event?.created_by_id === user?.id;

  // Find current user's RSVP status
  const myAttendee = useMemo(() => {
    if (!event || !user) return null;
    return event.attendees.find((a) => a.user_id === user.id) ?? null;
  }, [event, user]);

  const myRsvpStatus = myAttendee?.rsvp_status ?? null;

  // Error / loading states
  if (!Number.isFinite(parsedId)) {
    return <p className="text-destructive">{t("notFound")}</p>;
  }

  if (eventQuery.isLoading) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("loadingEvent")}
      </div>
    );
  }

  if (eventQuery.isError || !event) {
    const status = getHttpStatus(eventQuery.error);
    const backTo = gp("/events");
    const backLabel = t("backToEvents");

    if (status === 403) {
      return (
        <StatusMessage
          icon={<ShieldAlert />}
          title={t("noAccess")}
          description={t("noAccessDescription")}
          backTo={backTo}
          backLabel={backLabel}
        />
      );
    }
    return (
      <StatusMessage
        icon={<SearchX />}
        title={t("notFound")}
        description={t("notFoundDescription")}
        backTo={backTo}
        backLabel={backLabel}
      />
    );
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Breadcrumb>
          <BreadcrumbList>
            {initiativeName && (
              <>
                <BreadcrumbItem>
                  <BreadcrumbLink asChild>
                    <Link to={gp(`/initiatives/${event.initiative_id}`)}>{initiativeName}</Link>
                  </BreadcrumbLink>
                </BreadcrumbItem>
                <BreadcrumbSeparator />
              </>
            )}
            <BreadcrumbItem>
              <BreadcrumbLink asChild>
                <Link to={gp("/events")}>{t("title")}</Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage>{event.title}</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>

        <div className="flex items-center gap-2">
          {event.all_day && <Badge variant="secondary">{t("allDay")}</Badge>}
          <Button variant="ghost" size="sm" asChild>
            <Link to={gp(`/events/${event.id}/settings`)}>
              <Settings className="h-4 w-4" />
            </Link>
          </Button>
          {isOwner && (
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive"
              onClick={() => setDeleteConfirmOpen(true)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>

      {/* Event title and description */}
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">{event.title}</h1>
        {event.description && <p className="text-muted-foreground text-sm">{event.description}</p>}
      </div>

      {/* Date, time, and location details */}
      <Card>
        <CardContent className="space-y-4 pt-6">
          <div className="flex items-start gap-3">
            <CalendarDays className="text-muted-foreground mt-0.5 h-5 w-5 shrink-0" />
            <div>
              <p className="font-medium">
                {formatDateRange(event.start_at, event.end_at, event.all_day)}
              </p>
            </div>
          </div>

          {event.location && (
            <div className="flex items-start gap-3">
              <MapPin className="text-muted-foreground mt-0.5 h-5 w-5 shrink-0" />
              <p className="text-sm">{event.location}</p>
            </div>
          )}

          {event.color && (
            <div className="flex items-center gap-3">
              <span
                className="inline-block h-5 w-5 shrink-0 rounded-full border"
                style={{ backgroundColor: event.color }}
              />
              <span className="text-muted-foreground text-sm">{t("color")}</span>
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
              <span className="text-muted-foreground text-sm">{t("rsvp")}:</span>
              {myRsvpStatus && (
                <Badge variant={rsvpBadgeVariant(myRsvpStatus)}>
                  {t(rsvpLabelKey(myRsvpStatus))}
                </Badge>
              )}
              <Select
                value={myRsvpStatus ?? "pending"}
                onValueChange={(value) => updateRSVP.mutate({ rsvp_status: value as RSVPStatus })}
                disabled={updateRSVP.isPending}
              >
                <SelectTrigger className="w-[140px]">
                  <SelectValue />
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
                  <span className="text-sm font-medium">
                    {attendee.user?.full_name?.trim() ||
                      attendee.user?.email ||
                      `User #${attendee.user_id}`}
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

      {/* Custom Properties — read-only view; edits happen on the Settings page. */}
      {event.property_values.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-lg">{t("properties")}</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {event.property_values.map((property) => {
                const Icon = iconForPropertyType(property.type);
                return (
                  <li
                    key={property.property_id}
                    className="grid grid-cols-[minmax(0,8rem)_1fr] items-center gap-2"
                  >
                    <span className="text-muted-foreground flex min-w-0 items-center gap-1.5 text-xs font-normal">
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

      {/* Delete Event Confirmation */}
      <ConfirmDialog
        open={deleteConfirmOpen}
        onOpenChange={setDeleteConfirmOpen}
        title={t("deleteEvent")}
        description={t("deleteEventConfirm")}
        confirmLabel={t("deleteEvent")}
        cancelLabel={t("common:cancel")}
        onConfirm={() => deleteEvent.mutate(parsedId)}
        isLoading={deleteEvent.isPending}
        destructive
      />
    </div>
  );
}
