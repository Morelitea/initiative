import { Link, useParams, useRouter } from "@tanstack/react-router";
import { Copy, Loader2, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ShareControl } from "@/components/access/ShareControl";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  useCounterGroup,
  useDeleteCounterGroup,
  useDuplicateCounterGroup,
  useSetCounterGroupGrants,
  useUpdateCounterGroup,
} from "@/hooks/useCounters";
import { toast } from "@/lib/chesterToast";
import { useGuildPath } from "@/lib/guildUrl";

export function CounterGroupSettingsPage() {
  const { t } = useTranslation(["counters", "common", "access"]);
  const { groupId } = useParams({ strict: false }) as { groupId?: string };
  const parsedId = groupId ? Number(groupId) : Number.NaN;
  const router = useRouter();
  const gp = useGuildPath();

  // ── Fetch group ────────────────────────────────────────────────────────

  const groupQuery = useCounterGroup(Number.isFinite(parsedId) ? parsedId : null);
  const group = groupQuery.data;

  const canManage =
    group?.my_permission_level === "owner" || group?.my_permission_level === "write";
  const isOwner = group?.my_permission_level === "owner";

  // ── Details tab ────────────────────────────────────────────────────────

  const [nameValue, setNameValue] = useState("");
  const [descriptionValue, setDescriptionValue] = useState("");

  useEffect(() => {
    if (!group) return;
    setNameValue(group.name);
    setDescriptionValue(group.description ?? "");
  }, [group]);

  const updateGroup = useUpdateCounterGroup(parsedId, {
    onSuccess: () => {
      toast.success(t("groupUpdated"));
    },
  });

  const handleDetailsSave = () => {
    const trimmedName = nameValue.trim();
    if (!trimmedName) return;
    updateGroup.mutate({
      name: trimmedName,
      description: descriptionValue.trim() || null,
    });
  };

  // ── Access tab (unified grants) ────────────────────────────────────────

  const setGrants = useSetCounterGroupGrants(parsedId, {
    onSuccess: () =>
      toast.success(t("permissionsUpdated", { defaultValue: "Permissions updated" })),
  });

  // ── Duplicate ──────────────────────────────────────────────────────────

  const [duplicateDialogOpen, setDuplicateDialogOpen] = useState(false);
  const [duplicateName, setDuplicateName] = useState("");

  const duplicateGroup = useDuplicateCounterGroup(parsedId, {
    onSuccess: (created) => {
      toast.success(t("duplicate.success"));
      setDuplicateDialogOpen(false);
      router.navigate({ to: gp(`/counter-groups/${created.id}/settings`) });
    },
  });

  const openDuplicateDialog = () => {
    setDuplicateName(group ? t("duplicate.defaultName", { name: group.name }) : "");
    setDuplicateDialogOpen(true);
  };

  const handleDuplicate = () => {
    const trimmed = duplicateName.trim();
    duplicateGroup.mutate({ name: trimmed || undefined });
  };

  // ── Delete ─────────────────────────────────────────────────────────────

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const deleteGroup = useDeleteCounterGroup({
    onSuccess: () => {
      toast.success(t("groupDeleted"));
      setDeleteDialogOpen(false);
      router.navigate({ to: gp("/counter-groups") });
    },
  });

  // ── Early returns ──────────────────────────────────────────────────────

  if (!Number.isFinite(parsedId)) {
    return <p className="text-destructive">{t("notFound")}</p>;
  }

  if (groupQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("loadingGroup")}
      </div>
    );
  }

  if (groupQuery.isError || !group) {
    return <p className="text-destructive">{t("notFound")}</p>;
  }

  const ownerId = group.grants.find((g) => g.level === "owner")?.user_id ?? null;

  return (
    <div className="space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp("/counter-groups")}>{t("title")}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp(`/counter-groups/${group.id}`)}>{group.name}</Link>
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
                <Label htmlFor="counter-group-name">{t("name")}</Label>
                <Input
                  id="counter-group-name"
                  value={nameValue}
                  onChange={(e) => setNameValue(e.target.value)}
                  placeholder={t("namePlaceholder")}
                  disabled={!canManage}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="counter-group-description">{t("description")}</Label>
                <Textarea
                  id="counter-group-description"
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
                  disabled={updateGroup.isPending || !nameValue.trim()}
                >
                  {updateGroup.isPending ? t("saving") : t("common:save")}
                </Button>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Access tab ──────────────────────────────────────────── */}
        {/* Write access can manage permissions; only deleting the group is
            owner-only (handled in the Advanced tab). */}
        {canManage && (
          <TabsContent value="access" className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>{t("access")}</CardTitle>
                <CardDescription>{t("access:share.restrictedHint")}</CardDescription>
              </CardHeader>
              <CardContent>
                <ShareControl
                  initiativeId={group.initiative_id}
                  grants={group.grants}
                  ownerId={ownerId}
                  onChange={(grants) => setGrants.mutate(grants)}
                  disabled={!isOwner || setGrants.isPending}
                />
              </CardContent>
            </Card>
          </TabsContent>
        )}

        {/* ── Advanced tab ────────────────────────────────────────── */}
        <TabsContent value="advanced" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>{t("duplicate.title")}</CardTitle>
              <CardDescription>{t("duplicate.description")}</CardDescription>
            </CardHeader>
            <CardContent>
              <Button type="button" variant="outline" onClick={openDuplicateDialog}>
                <Copy className="mr-2 h-4 w-4" />
                {t("duplicate.action")}
              </Button>
            </CardContent>
          </Card>

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
                  <Trash2 className="mr-2 h-4 w-4" />
                  {t("deleteGroup")}
                </Button>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>

      <Dialog open={duplicateDialogOpen} onOpenChange={setDuplicateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("duplicate.title")}</DialogTitle>
            <DialogDescription>{t("duplicate.dialogDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="duplicate-counter-group-name">{t("name")}</Label>
            <Input
              id="duplicate-counter-group-name"
              value={duplicateName}
              onChange={(e) => setDuplicateName(e.target.value)}
              placeholder={t("namePlaceholder")}
              onKeyDown={(e) => {
                if (e.key === "Enter" && duplicateName.trim()) handleDuplicate();
              }}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDuplicateDialogOpen(false)}
              disabled={duplicateGroup.isPending}
            >
              {t("common:cancel")}
            </Button>
            <Button
              type="button"
              onClick={handleDuplicate}
              disabled={duplicateGroup.isPending || !duplicateName.trim()}
            >
              {duplicateGroup.isPending ? t("duplicate.duplicating") : t("duplicate.action")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        title={t("deleteGroup")}
        description={t("deleteGroupConfirm")}
        confirmLabel={t("deleteGroup")}
        cancelLabel={t("common:cancel")}
        onConfirm={() => deleteGroup.mutate(parsedId)}
        isLoading={deleteGroup.isPending}
        destructive
      />
    </div>
  );
}
