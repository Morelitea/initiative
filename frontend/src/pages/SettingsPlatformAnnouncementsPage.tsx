import { Lock, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { AnnouncementAdminRead } from "@/api/generated/initiativeAPI.schemas";
import { AnnouncementEditorDialog } from "@/components/announcements/AnnouncementEditorDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useDeleteAnnouncement, usePlatformAnnouncements } from "@/hooks/useAnnouncementsAdmin";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { formatDateTime } from "@/lib/formatDate";

type Status = "draft" | "scheduled" | "live" | "expired";

const statusOf = (announcement: AnnouncementAdminRead, now: number): Status => {
  if (!announcement.published_at) return "draft";
  if (new Date(announcement.published_at).getTime() > now) return "scheduled";
  if (announcement.expires_at && new Date(announcement.expires_at).getTime() <= now) {
    return "expired";
  }
  return "live";
};

const STATUS_VARIANT: Record<Status, "default" | "secondary" | "outline"> = {
  draft: "outline",
  scheduled: "secondary",
  live: "default",
  expired: "outline",
};

/**
 * Where the deployment's notices are written.
 *
 * Both kinds are listed: the ones authored here, and the ones compiled into
 * this build (shown read-only — they are changed by shipping a release).
 */
export const SettingsPlatformAnnouncementsPage = () => {
  const { t } = useTranslation(["announcements", "common"]);
  const { data, isLoading } = usePlatformAnnouncements();
  const remove = useDeleteAnnouncement();

  const [editing, setEditing] = useState<AnnouncementAdminRead | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<AnnouncementAdminRead | null>(null);

  const items = data?.items ?? [];
  const now = Date.now();

  const handleDelete = async () => {
    if (!pendingDelete?.id) return;
    try {
      await remove.mutateAsync(pendingDelete.id);
      toast.success(t("admin.deleted"));
    } catch (error) {
      toast.error(getErrorMessage(error, "announcements:admin.deleteFailed"));
    } finally {
      setPendingDelete(null);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>{t("admin.title")}</CardTitle>
            <CardDescription>{t("admin.subtitle")}</CardDescription>
          </div>
          <Button
            onClick={() => {
              setEditing(null);
              setEditorOpen(true);
            }}
          >
            <Plus className="mr-1 h-4 w-4" />
            {t("admin.new")}
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {isLoading ? (
            <>
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
            </>
          ) : items.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("admin.empty")}</p>
          ) : (
            items.map((announcement) => {
              const status = statusOf(announcement, now);
              return (
                <div
                  key={announcement.key}
                  className="flex flex-col gap-3 rounded-md border p-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{announcement.title}</span>
                      <Badge variant={STATUS_VARIANT[status]}>{t(`admin.status.${status}`)}</Badge>
                      <Badge variant="secondary">{t(`category.${announcement.category}`)}</Badge>
                      {announcement.is_builtin ? (
                        <Badge variant="outline" className="gap-1">
                          <Lock className="h-3 w-3" />
                          {t("admin.builtin")}
                        </Badge>
                      ) : null}
                    </div>
                    <p className="text-muted-foreground text-xs">
                      {announcement.published_at
                        ? t("admin.publishedOn", {
                            date: formatDateTime(announcement.published_at),
                          })
                        : t("admin.notPublished")}
                      {" · "}
                      {t("admin.audience", {
                        role: t(`admin.roles.${announcement.min_platform_role ?? "member"}`),
                      })}
                      {announcement.guild_admins_only ? ` · ${t("admin.guildAdminsOnly")}` : ""}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={announcement.is_builtin}
                      onClick={() => {
                        setEditing(announcement);
                        setEditorOpen(true);
                      }}
                    >
                      <Pencil className="mr-1 h-4 w-4" />
                      {t("common:edit")}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      disabled={announcement.is_builtin}
                      aria-label={t("common:delete")}
                      onClick={() => setPendingDelete(announcement)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              );
            })
          )}
        </CardContent>
      </Card>

      <AnnouncementEditorDialog
        open={editorOpen}
        announcement={editing}
        onOpenChange={setEditorOpen}
      />

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        title={t("admin.deleteTitle")}
        description={t("admin.deleteDescription", { title: pendingDelete?.title ?? "" })}
        confirmLabel={t("common:delete")}
        onConfirm={() => void handleDelete()}
      />
    </div>
  );
};
