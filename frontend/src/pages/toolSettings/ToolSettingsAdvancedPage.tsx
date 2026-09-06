/**
 * `/settings/advanced` — the tool's own extra operations, and deletion.
 *
 * Deleting is the owner's alone, so the danger card is absent for everyone
 * else however they reached the address.
 */

import { useRouter } from "@tanstack/react-router";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useToolSettings } from "@/components/tools/settings/ToolSettingsContext";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { toast } from "@/lib/chesterToast";
import { useGuildPath } from "@/lib/guildUrl";
import { toolGuildBrowseTarget, toolListRoute } from "@/lib/tools";

export const ToolSettingsAdvancedPage = () => {
  const { t } = useTranslation("common");
  const router = useRouter();
  const gp = useGuildPath();
  const { tool, entity, isOwner, remove, advancedExtra } = useToolSettings();

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

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
