import { Link, useParams, useRouter } from "@tanstack/react-router";
import { Loader2, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ShareControl } from "@/components/access/ShareControl";
import { TagPicker } from "@/components/tags";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  useCalendar,
  useDeleteCalendar,
  useSetCalendarGrants,
  useUpdateCalendar,
} from "@/hooks/useCalendars";
import { useSetToolTags } from "@/hooks/useToolTags";
import { toast } from "@/lib/chesterToast";
import { useGuildPath } from "@/lib/guildUrl";

/** The calendar's single sharing surface — name/color/description, the Access
 * card (grants), and the danger zone. Events inherit all of it. */
export function CalendarSettingsPage() {
  const { t } = useTranslation(["calendars", "common", "access"]);
  const router = useRouter();
  const gp = useGuildPath();
  const { calendarId: calendarIdParam } = useParams({ strict: false });
  const calendarId = Number(calendarIdParam);

  const { data: calendar, isLoading } = useCalendar(
    Number.isFinite(calendarId) ? calendarId : null
  );

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [color, setColor] = useState("");
  const [tags, setTags] = useState<TagSummary[]>([]);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  useEffect(() => {
    if (calendar) {
      setName(calendar.name);
      setDescription(calendar.description ?? "");
      setColor(calendar.color ?? "");
      setTags(calendar.tags ?? []);
    }
  }, [calendar]);

  const updateCalendar = useUpdateCalendar(calendarId, {
    onSuccess: () => toast.success(t("detailsUpdated")),
  });

  const setGrants = useSetCalendarGrants(calendarId, {
    onSuccess: () => toast.success(t("detailsUpdated")),
  });

  const setCalendarTags = useSetToolTags(Tool.calendar);

  // Tags persist immediately on change (like tasks/documents), no Save button.
  const handleTagsChange = (newTags: TagSummary[]) => {
    const previous = tags;
    setTags(newTags);
    setCalendarTags.mutate(
      { id: calendarId, tagIds: newTags.map((tag) => tag.id) },
      { onError: () => setTags(previous) }
    );
  };

  const deleteCalendar = useDeleteCalendar({
    onSuccess: () => {
      toast.success(t("calendarDeleted"));
      void router.navigate({ to: gp("/calendars") });
    },
  });

  const handleSave = () => {
    const trimmedName = name.trim();
    if (!trimmedName) return;
    updateCalendar.mutate({
      name: trimmedName,
      description: description.trim() || null,
      color: color || null,
    });
  };

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 p-8 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("loading")}
      </div>
    );
  }

  if (!calendar) {
    return (
      <div className="p-8 text-center">
        <p className="text-muted-foreground">{t("calendarNotFound")}</p>
        <Button variant="link" asChild className="mt-2">
          <Link to={gp("/calendars")}>{t("backToCalendar")}</Link>
        </Button>
      </div>
    );
  }

  const isOwner = calendar.my_permission_level === "owner";

  return (
    <div className="space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp("/calendars")}>{t("title")}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{calendar.name}</BreadcrumbPage>
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
            <Label htmlFor="calendar-name">{t("calendarName")}</Label>
            <Input id="calendar-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>

          <div className="space-y-2">
            <Label htmlFor="calendar-description">{t("description")}</Label>
            <Textarea
              id="calendar-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="calendar-color">{t("calendarColor")}</Label>
            <ColorPickerPopover
              id="calendar-color"
              value={color || "#6366F1"}
              onChange={setColor}
              triggerLabel={t("calendarColor")}
            />
          </div>

          <Button onClick={handleSave} disabled={updateCalendar.isPending || !name.trim()}>
            {updateCalendar.isPending ? (
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

      {/* Access — the ONLY sharing surface; every event inherits it. */}
      <Card>
        <CardHeader>
          <CardTitle>{t("access")}</CardTitle>
          <CardDescription>{t("access:share.settingsDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <ShareControl
            initiativeId={calendar.initiative_id}
            grants={calendar.grants}
            ownerId={calendar.grants.find((g) => g.level === "owner")?.user_id ?? null}
            onChange={(grants) => setGrants.mutate(grants)}
            disabled={!isOwner || setGrants.isPending}
          />
        </CardContent>
      </Card>

      {/* Danger Zone */}
      <Card className="border-destructive/50">
        <CardHeader>
          <CardTitle className="text-destructive">{t("dangerZone")}</CardTitle>
          <CardDescription>{t("calendarDangerZoneDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            variant="destructive"
            onClick={() => setDeleteConfirmOpen(true)}
            disabled={deleteCalendar.isPending}
          >
            <Trash2 className="h-4 w-4" />
            {t("deleteCalendar")}
          </Button>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={deleteConfirmOpen}
        onOpenChange={setDeleteConfirmOpen}
        title={t("deleteCalendar")}
        description={t("deleteCalendarConfirm")}
        confirmLabel={t("deleteCalendar")}
        destructive
        onConfirm={() => deleteCalendar.mutate(calendarId)}
        isLoading={deleteCalendar.isPending}
      />
    </div>
  );
}
