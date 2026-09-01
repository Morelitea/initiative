/**
 * `/settings/advanced` — the comment switch, the tool's own extra operations,
 * and deletion.
 *
 * Deleting is the owner's alone, so the danger card is absent for everyone
 * else however they reached the address.
 */

import { useRouter } from "@tanstack/react-router";
import { Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useToolSettings } from "@/components/tools/settings/ToolSettingsContext";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Switch } from "@/components/ui/switch";
import { useSetToolComments } from "@/hooks/useToolComments";
import { toast } from "@/lib/chesterToast";
import { useGuildPath } from "@/lib/guildUrl";
import { toolGuildBrowseTarget, toolListRoute } from "@/lib/tools";

export const ToolSettingsAdvancedPage = () => {
  const { t } = useTranslation("common");
  const router = useRouter();
  const gp = useGuildPath();
  const { tool, entity, canManage, isOwner, remove, advancedExtra } = useToolSettings();

  const [commentsDisabled, setCommentsDisabled] = useState(entity.comments_disabled);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  useEffect(() => {
    setCommentsDisabled(entity.comments_disabled);
  }, [entity]);

  const setToolComments = useSetToolComments(tool);

  const handleDelete = () => {
    remove.mutate(entity.id, {
      onSuccess: () => {
        toast.success(t("toolSettings.deleted", { name: entity.name }));
        setDeleteDialogOpen(false);
        // Back to the tool's tab in the initiative this entity belonged to.
        // A guild-level entity (an app's calendar) has no tab, so it falls back
        // to the guild home browsing that tool.
        if (entity.initiative_id == null) {
          const browse = toolGuildBrowseTarget(tool);
          router.navigate({ to: gp(browse.to), search: browse.search });
        } else {
          router.navigate({ to: gp(toolListRoute(tool, entity.initiative_id)) });
        }
      },
    });
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div>
            <CardTitle>{t("toolSettings.comments")}</CardTitle>
            <CardDescription>{t("toolSettings.commentsDescription")}</CardDescription>
          </div>
          <Switch
            id="tool-settings-comments-disabled"
            checked={commentsDisabled}
            onCheckedChange={(value) => {
              // The switch shows the new state immediately and puts the old
              // one back if the write fails, like the tag picker on Details.
              const previous = commentsDisabled;
              setCommentsDisabled(value);
              setToolComments.mutate(
                { id: entity.id, disabled: value },
                { onError: () => setCommentsDisabled(previous) }
              );
            }}
            disabled={!canManage || setToolComments.isPending}
            aria-label={t("toolSettings.commentsToggle")}
          />
        </CardHeader>
      </Card>

      {advancedExtra}

      {isOwner && (
        <Card className="border-destructive/40 bg-destructive/5 shadow-sm">
          <CardHeader>
            <CardTitle>{t("toolSettings.dangerZone")}</CardTitle>
            <CardDescription>{t("toolSettings.dangerZoneDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            <Button type="button" variant="destructive" onClick={() => setDeleteDialogOpen(true)}>
              <Trash2 className="h-4 w-4" />
              {t("delete")}
            </Button>
          </CardContent>
        </Card>
      )}

      <ConfirmDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        title={t("toolSettings.deleteConfirmTitle", { name: entity.name })}
        description={t("toolSettings.deleteConfirmDescription")}
        confirmLabel={t("delete")}
        cancelLabel={t("cancel")}
        onConfirm={handleDelete}
        isLoading={remove.isPending}
        destructive
      />
    </div>
  );
};
