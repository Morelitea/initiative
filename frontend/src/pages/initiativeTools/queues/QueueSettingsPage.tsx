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
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useDeleteQueue, useQueue, useSetQueueGrants, useUpdateQueue } from "@/hooks/useQueues";
import { useSetToolTags } from "@/hooks/useToolTags";
import { toast } from "@/lib/chesterToast";
import { useGuildPath } from "@/lib/guildUrl";

export const QueueSettingsPage = () => {
  const { t } = useTranslation(["queues", "common", "access"]);
  const { queueId } = useParams({ strict: false }) as { queueId: string };
  const parsedId = Number(queueId);
  const router = useRouter();
  const gp = useGuildPath();

  const queueQuery = useQueue(Number.isFinite(parsedId) ? parsedId : null);
  const queue = queueQuery.data;

  const canManage =
    queue?.my_permission_level === "owner" || queue?.my_permission_level === "write";
  const isOwner = queue?.my_permission_level === "owner";

  // ── Details ────────────────────────────────────────────────────────────

  const [nameValue, setNameValue] = useState("");
  const [descriptionValue, setDescriptionValue] = useState("");
  const [tags, setTags] = useState<TagSummary[]>([]);

  useEffect(() => {
    if (!queue) return;
    setNameValue(queue.name);
    setDescriptionValue(queue.description ?? "");
    setTags(queue.tags ?? []);
  }, [queue]);

  const updateQueue = useUpdateQueue(parsedId, {
    onSuccess: () => toast.success(t("detailsUpdated")),
  });

  const setQueueTags = useSetToolTags(Tool.queue);

  const handleDetailsSave = () => {
    const trimmedName = nameValue.trim();
    if (!trimmedName) return;
    updateQueue.mutate({ name: trimmedName, description: descriptionValue.trim() || null });
  };

  // ── Access (unified grants) ─────────────────────────────────────────────

  const setGrants = useSetQueueGrants(parsedId, {
    onSuccess: () => toast.success(t("permissionsUpdated")),
  });

  // ── Delete ─────────────────────────────────────────────────────────────

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const deleteQueue = useDeleteQueue({
    onSuccess: () => {
      toast.success(t("queueDeleted"));
      setDeleteDialogOpen(false);
      router.navigate({ to: gp("/queues") });
    },
  });

  // ── Early returns ──────────────────────────────────────────────────────

  if (!Number.isFinite(parsedId)) {
    return <p className="text-destructive">{t("notFound")}</p>;
  }

  if (queueQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("loadingQueue")}
      </div>
    );
  }

  if (queueQuery.isError || !queue) {
    return <p className="text-destructive">{t("notFound")}</p>;
  }

  const ownerId = queue.grants.find((g) => g.level === "owner")?.user_id ?? null;
  const isQueueOwner = queue.my_permission_level === "owner";

  return (
    <div className="space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp("/queues")}>{t("title")}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp(`/queues/${queue.id}`)}>{queue.name}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{t("settings")}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div className="space-y-1">
        <h1 className="font-semibold text-3xl tracking-tight">{t("settings")}</h1>
        <p className="text-muted-foreground text-sm">{t("settingsDescription")}</p>
      </div>

      <Tabs defaultValue="details" className="space-y-4">
        <TabsList className="w-full max-w-xl justify-start">
          <TabsTrigger value="details">{t("details")}</TabsTrigger>
          {canManage && <TabsTrigger value="access">{t("access")}</TabsTrigger>}
          <TabsTrigger value="advanced">{t("advanced")}</TabsTrigger>
        </TabsList>

        {/* ── Details tab ─────────────────────────────────────────── */}
        <TabsContent value="details" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>{t("details")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="queue-name">{t("name")}</Label>
                <Input
                  id="queue-name"
                  value={nameValue}
                  onChange={(e) => setNameValue(e.target.value)}
                  placeholder={t("namePlaceholder")}
                  disabled={!canManage}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="queue-description">{t("description")}</Label>
                <Textarea
                  id="queue-description"
                  value={descriptionValue}
                  onChange={(e) => setDescriptionValue(e.target.value)}
                  placeholder={t("descriptionPlaceholder")}
                  disabled={!canManage}
                  rows={3}
                />
              </div>
              {canManage && (
                <Button
                  onClick={handleDetailsSave}
                  disabled={updateQueue.isPending || !nameValue.trim()}
                >
                  {updateQueue.isPending ? t("saving") : t("common:save")}
                </Button>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("tags")}</CardTitle>
              <CardDescription>{t("tagsDescription")}</CardDescription>
            </CardHeader>
            <CardContent>
              {canManage ? (
                <TagPicker
                  selectedTags={tags}
                  onChange={(newTags) => {
                    setTags(newTags);
                    setQueueTags.mutate({
                      id: parsedId,
                      tagIds: newTags.map((tag) => tag.id),
                    });
                  }}
                />
              ) : (
                <p className="text-muted-foreground text-sm">{t("noWriteAccessTags")}</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Access tab ──────────────────────────────────────────── */}
        {canManage && (
          <TabsContent value="access" className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>{t("access")}</CardTitle>
                <CardDescription>{t("access:share.settingsDescription")}</CardDescription>
              </CardHeader>
              <CardContent>
                <ShareControl
                  initiativeId={queue.initiative_id}
                  grants={queue.grants}
                  ownerId={ownerId}
                  onChange={(grants) => setGrants.mutate(grants)}
                  disabled={!isQueueOwner || setGrants.isPending}
                />
              </CardContent>
            </Card>
          </TabsContent>
        )}

        {/* ── Advanced tab ────────────────────────────────────────── */}
        <TabsContent value="advanced" className="space-y-6">
          {isOwner && (
            <Card className="border-destructive/40 bg-destructive/5 shadow-sm">
              <CardHeader>
                <CardTitle>{t("dangerZone")}</CardTitle>
                <CardDescription>{t("dangerZoneDescription")}</CardDescription>
              </CardHeader>
              <CardContent>
                <Button
                  type="button"
                  variant="destructive"
                  onClick={() => setDeleteDialogOpen(true)}
                  disabled={!isOwner}
                >
                  <Trash2 className="h-4 w-4" />
                  {t("deleteQueue")}
                </Button>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>

      <ConfirmDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        title={t("deleteQueue")}
        description={t("deleteQueueConfirm")}
        confirmLabel={t("deleteQueue")}
        cancelLabel={t("common:cancel")}
        onConfirm={() => deleteQueue.mutate(parsedId)}
        isLoading={deleteQueue.isPending}
        destructive
      />
    </div>
  );
};
