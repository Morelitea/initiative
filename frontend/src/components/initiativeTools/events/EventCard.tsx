import { Link } from "@tanstack/react-router";
import { CalendarDays, MapPin, Users } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PropertyValueCell } from "@/components/properties/PropertyValueCell";
import { nonEmptyPropertySummaries } from "@/components/properties/propertyHelpers";
import { useGuildPath } from "@/lib/guildUrl";
import { cn } from "@/lib/utils";
import type { CalendarEventSummary } from "@/api/generated/initiativeAPI.schemas";

interface EventCardProps {
  event: CalendarEventSummary;
  initiativeName?: string;
  className?: string;
}

/**
 * Format a date range for display.
 * Uses Intl.DateTimeFormat for locale-aware formatting.
 */
const formatDateRange = (startStr: string, endStr: string, allDay: boolean): string => {
  const start = new Date(startStr);
  const end = new Date(endStr);

  if (allDay) {
    const dateOpts: Intl.DateTimeFormatOptions = {
      month: "short",
      day: "numeric",
      year: "numeric",
    };
    const startDate = start.toLocaleDateString(undefined, dateOpts);
    const endDate = end.toLocaleDateString(undefined, dateOpts);
    // If same day, show just one date
    if (startDate === endDate) return startDate;
    return `${startDate} - ${endDate}`;
  }

  const dateTimeOpts: Intl.DateTimeFormatOptions = {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  };
  const startFormatted = start.toLocaleString(undefined, dateTimeOpts);
  const endFormatted = end.toLocaleString(undefined, dateTimeOpts);

  // If same day, abbreviate
  const sameDay =
    start.getFullYear() === end.getFullYear() &&
    start.getMonth() === end.getMonth() &&
    start.getDate() === end.getDate();

  if (sameDay) {
    const timeOpts: Intl.DateTimeFormatOptions = {
      hour: "numeric",
      minute: "2-digit",
    };
    const endTime = end.toLocaleString(undefined, timeOpts);
    return `${startFormatted} - ${endTime}`;
  }

  return `${startFormatted} - ${endFormatted}`;
};

export const EventCard = ({ event, initiativeName, className }: EventCardProps) => {
  const { t } = useTranslation("events");
  const gp = useGuildPath();

  return (
    <Link
      to={gp(`/events/${event.id}`)}
      className={cn(
        "group bg-card text-card-foreground hover:border-primary/50 block w-full overflow-hidden rounded-2xl border shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg",
        className
      )}
    >
      <Card className="border-0 shadow-none">
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="line-clamp-1 text-lg leading-tight">{event.title}</CardTitle>
            {event.all_day && (
              <Badge variant="secondary" className="shrink-0">
                {t("allDay")}
              </Badge>
            )}
          </div>
          {event.description && (
            <p className="text-muted-foreground line-clamp-2 text-sm">{event.description}</p>
          )}
        </CardHeader>
        <CardContent className="pt-0">
          <div className="text-muted-foreground flex flex-col gap-2 text-sm">
            <div className="flex items-center gap-1.5">
              <CalendarDays className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">
                {formatDateRange(event.start_at, event.end_at, event.all_day)}
              </span>
            </div>
            {event.location && (
              <div className="flex items-center gap-1.5">
                <MapPin className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{event.location}</span>
              </div>
            )}
            <div className="flex items-center gap-3">
              {initiativeName && <span className="truncate">{initiativeName}</span>}
              <Badge variant="outline" className="inline-flex items-center gap-1">
                <Users className="h-3 w-3" />
                {t("attendeeCount", { count: event.attendee_count })}
              </Badge>
            </div>
            {(() => {
              const propertyChips = nonEmptyPropertySummaries(event.property_values);
              if (propertyChips.length === 0) return null;
              return (
                <div className="flex flex-wrap gap-1">
                  {propertyChips.map((summary) => (
                    <PropertyValueCell key={summary.property_id} summary={summary} variant="chip" />
                  ))}
                </div>
              );
            })()}
          </div>
        </CardContent>
      </Card>
    </Link>
  );
};
