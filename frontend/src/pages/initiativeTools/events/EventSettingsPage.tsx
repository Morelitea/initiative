import { useEffect, useMemo, useState } from "react";
import { Link, useRouter, useParams } from "@tanstack/react-router";
import { Loader2, Trash2, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { toast } from "@/lib/chesterToast";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

import {
  useCalendarEvent,
  useUpdateCalendarEvent,
  useDeleteCalendarEvent,
  useSetEventAttendees,
} from "@/hooks/useCalendarEvents";
import { useInitiativeMembers } from "@/hooks/useInitiatives";
import { useGuildPath } from "@/lib/guildUrl";
import { AddPropertyButton, PropertyList } from "@/components/properties";
import type {
  PropertyDefinitionRead,
  PropertySummary,
} from "@/api/generated/initiativeAPI.schemas";

export function EventSettingsPage() {
  const { t } = useTranslation(["events", "common"]);
  const router = useRouter();
  const gp = useGuildPath();
  const { eventId: eventIdParam } = useParams({ strict: false });
  const eventId = Number(eventIdParam);

  const { data: event, isLoading } = useCalendarEvent(Number.isFinite(eventId) ? eventId : null);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [location, setLocation] = useState("");
  const [startAt, setStartAt] = useState("");
  const [endAt, setEndAt] = useState("");
  const [allDay, setAllDay] = useState(false);
  const [color, setColor] = useState("");
  const [attendeeIds, setAttendeeIds] = useState<number[]>([]);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  // Custom properties — staging pattern: newly-attached definitions land in
  // ``pendingProperties`` as stub summaries so they show up immediately in
  // the PropertyList. The list's debounced save handles persistence.
  const [pendingProperties, setPendingProperties] = useState<PropertyDefinitionRead[]>([]);

  // Fetch initiative members
  const { data: members } = useInitiativeMembers(event?.initiative_id ?? null);

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
    // Also include names from event attendees in case members haven't loaded
    for (const a of event?.attendees ?? []) {
      if (a.user && !map.has(a.user_id)) {
        map.set(a.user_id, a.user.full_name || a.user.email);
      }
    }
    return map;
  }, [members, event]);

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
      setStartAt(toLocalDateTimeString(new Date(event.start_at)));
      setEndAt(toLocalDateTimeString(new Date(event.end_at)));
      setAllDay(event.all_day);
      setColor(event.color ?? "");
      setAttendeeIds(event.attendees.map((a) => a.user_id));
    }
  }, [event]);

  const updateEvent = useUpdateCalendarEvent(eventId, {
    onSuccess: () => toast.success(t("detailsUpdated")),
  });

  const setAttendees = useSetEventAttendees(eventId, {
    onSuccess: () => toast.success(t("detailsUpdated")),
  });

  const deleteEvent = useDeleteCalendarEvent({
    onSuccess: () => {
      toast.success(t("eventDeleted"));
      void router.navigate({ to: gp("/events") });
    },
  });

  const handleSave = () => {
    const startValue = allDay ? `${startAt.split("T")[0]}T00:00:00` : startAt;
    const endValue = allDay ? `${endAt.split("T")[0]}T23:59:59` : endAt;

    updateEvent.mutate({
      title: title.trim() || undefined,
      description: description.trim() || undefined,
      location: location.trim() || undefined,
      start_at: startValue ? new Date(startValue).toISOString() : undefined,
      end_at: endValue ? new Date(endValue).toISOString() : undefined,
      all_day: allDay,
      color: color || undefined,
    });
  };

  const handleSaveAttendees = () => {
    setAttendees.mutate(attendeeIds);
  };

  if (isLoading) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 p-8 text-sm">
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
          <Link to={gp("/events")}>{t("backToEvents")}</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp("/events")}>{t("title")}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp(`/events/${eventId}`)}>{event.title}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{t("settings")}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

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
                <Label htmlFor="event-start">{t("startDate")}</Label>
                <Input
                  id="event-start"
                  type="date"
                  value={startAt.split("T")[0]}
                  onChange={(e) => setStartAt(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="event-end">{t("endDate")}</Label>
                <Input
                  id="event-end"
                  type="date"
                  value={endAt.split("T")[0]}
                  onChange={(e) => setEndAt(e.target.value)}
                  min={startAt.split("T")[0] || undefined}
                />
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <Label htmlFor="event-start">{t("startDate")}</Label>
              <Input
                id="event-start"
                type="datetime-local"
                value={startAt}
                onChange={(e) => setStartAt(e.target.value)}
              />
              <Label htmlFor="event-end">{t("endDate")}</Label>
              <Input
                id="event-end"
                type="datetime-local"
                value={endAt}
                onChange={(e) => setEndAt(e.target.value)}
              />
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="event-color">{t("color")}</Label>
            <Input
              id="event-color"
              type="color"
              value={color || "#6366f1"}
              onChange={(e) => setColor(e.target.value)}
              className="h-10 w-20"
            />
          </div>

          <Button onClick={handleSave} disabled={updateEvent.isPending}>
            {updateEvent.isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
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
            <div className="flex flex-wrap gap-1.5">
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

          <Button onClick={handleSaveAttendees} disabled={setAttendees.isPending}>
            {setAttendees.isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {t("saving")}
              </>
            ) : (
              t("common:save")
            )}
          </Button>
        </CardContent>
      </Card>

      {/* Custom Properties */}
      <Card>
        <CardHeader>
          <CardTitle>{t("properties")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <PropertyList entityKind="event" entityId={eventId} properties={combinedProperties} />
          <AddPropertyButton
            initiativeId={event.initiative_id}
            currentPropertyIds={combinedPropertyIds}
            onAdd={handleAddProperty}
          />
        </CardContent>
      </Card>

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
            <Trash2 className="mr-2 h-4 w-4" />
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

function toLocalDateTimeString(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
