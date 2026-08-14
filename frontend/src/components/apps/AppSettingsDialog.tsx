/**
 * One app's settings, opened from wherever the app is.
 *
 * **Every installed app has this**, whether or not it has a page of its own —
 * there is always something a person may want to check or take back. For an app
 * whose whole purpose is a credential it opens where the member clicked rather
 * than sending them to hunt through guild settings; for an app with a page it
 * is the gear beside its entry.
 *
 * What shows is scoped to what the viewer actually controls, which is not the
 * same as what they can see:
 *
 * - **Everyone** gets the two answers that are theirs — whether the app may act
 *   as them, and their own half of any connection. Nobody else's appears.
 * - **A guild admin** additionally gets what the guild owns: the guild-wide
 *   credential, where the app appears, and the governance view of what every
 *   member has given it.
 *
 * This is deliberately not the guild-settings page. That one is about the
 * install — adding, renaming, turning off, removing — and belongs to admins.
 * This one is about a person's own relationship with an app that is already
 * there.
 */

import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AppConnectionsPanel } from "@/components/apps/AppConnectionsPanel";
import { AppDelegationPanel } from "@/components/apps/AppDelegationPanel";
import { AppMembersPanel } from "@/components/apps/AppMembersPanel";
import { AppPlacementPanel } from "@/components/apps/AppPlacementPanel";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { useGuildAppDetail } from "@/hooks/useGuildAppDetail";
import { appEmbeds } from "@/lib/appSurfaces";

/** Only an admin reaches the placement control, and an admin clears every rung. */
const ADMIN = { isGuildAdmin: true };

export interface AppSettingsDialogProps {
  appId: number;
  /** Guild connections are an admin's to fill in; personal ones are everyone's. */
  isGuildAdmin: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AppSettingsDialog({
  appId,
  isGuildAdmin,
  open,
  onOpenChange,
}: AppSettingsDialogProps) {
  const { t } = useTranslation(["apps", "common"]);
  const detail = useGuildAppDetail(appId);
  const app = detail.data;

  const showsPlacement =
    isGuildAdmin && !!app && appEmbeds(app.definition, "initiative", ADMIN).length > 0;
  const showsAdminSection = isGuildAdmin && !!app;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{app?.name ?? t("apps:title")}</DialogTitle>
          <DialogDescription>{t("apps:settings.description")}</DialogDescription>
        </DialogHeader>
        {detail.isLoading || !app ? (
          <div className="flex items-center gap-2 py-6 text-muted-foreground text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("common:loading")}
          </div>
        ) : (
          <div className="space-y-6">
            {/* Yours first. An app that acts as people asks the question of
                everybody, admins included — a guild admin's own name is not
                something their role answers for. */}
            {app.delegates && (
              <AppDelegationPanel appId={app.id} appName={app.name} delegation={app.delegation} />
            )}

            <AppConnectionsPanel
              appId={app.id}
              connections={app.connections}
              isGuildAdmin={isGuildAdmin}
            />

            {showsAdminSection && (
              <>
                <Separator />
                <div className="space-y-1">
                  <h2 className="font-medium text-sm">{t("apps:settings.adminTitle")}</h2>
                  <p className="text-muted-foreground text-xs">
                    {t("apps:settings.adminDescription")}
                  </p>
                </div>
                {/* Where the app goes is the guild's call, and only for an app
                    that has somewhere to go. */}
                {showsPlacement && <AppPlacementPanel app={app} />}
                <AppMembersPanel appId={app.id} enabled />
              </>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
