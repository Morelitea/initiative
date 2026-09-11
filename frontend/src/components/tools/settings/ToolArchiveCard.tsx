/**
 * Putting a tool away, and taking it back out.
 *
 * One card for every tool, in the settings section they all share, because
 * archiving is one pair of endpoints for every kind — the set of things that
 * can be archived is the `Tool` enum, so anything that grows the enum gets this
 * without being wired up again.
 *
 * The two directions read different fields, which is the whole point of the
 * card. Archiving is an ordinary write and asks `my_permission_level`.
 * Unarchiving cannot: an archived entity reports `read` there — the server caps
 * it, so every edit affordance goes off at once — so the way back out is its
 * own server-computed answer, `can_unarchive`. Reading the cap for both is what
 * left archived content with no way back.
 */

import { Archive, ArchiveRestore } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ArchivableType } from "@/api/generated/initiativeAPI.schemas";
import { useToolSettings } from "@/components/tools/settings/ToolSettingsContext";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useArchiveEntity, useUnarchiveEntity } from "@/hooks/useArchive";
import { toast } from "@/lib/chesterToast";

/** Whether this viewer has anything to do here — what gates the card and, in
 *  the layout, the tab that holds it. */
export const canUseArchiveCard = (entity: {
  archived_at: string | null;
  can_unarchive: boolean;
  my_permission_level: string | null;
}): boolean =>
  entity.archived_at !== null
    ? entity.can_unarchive
    : entity.my_permission_level === "owner" || entity.my_permission_level === "write";

export const ToolArchiveCard = () => {
  const { t } = useTranslation("common");
  const { tool, entity } = useToolSettings();

  const archive = useArchiveEntity({
    onSuccess: () => toast.success(t("toolSettings.archive.archived", { name: entity.name })),
  });
  const unarchive = useUnarchiveEntity({
    onSuccess: () => toast.success(t("toolSettings.archive.unarchived", { name: entity.name })),
  });

  const isArchived = entity.archived_at !== null;
  const action = isArchived ? unarchive : archive;
  const target = { entityType: tool as ArchivableType, entityId: entity.id };

  if (!canUseArchiveCard(entity)) {
    return null;
  }

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>{t("toolSettings.archive.title")}</CardTitle>
        <CardDescription>
          {isArchived ? t("toolSettings.archive.isArchived") : t("toolSettings.archive.isActive")}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button
          type="button"
          variant="outline"
          onClick={() => action.mutate(target)}
          disabled={action.isPending}
        >
          {isArchived ? (
            <>
              <ArchiveRestore className="h-4 w-4" />
              {action.isPending
                ? t("toolSettings.archive.unarchiving")
                : t("toolSettings.archive.unarchive")}
            </>
          ) : (
            <>
              <Archive className="h-4 w-4" />
              {action.isPending
                ? t("toolSettings.archive.archiving")
                : t("toolSettings.archive.archive")}
            </>
          )}
        </Button>
      </CardContent>
    </Card>
  );
};
