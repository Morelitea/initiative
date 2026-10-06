/**
 * One app's settings, opened from wherever the app is.
 *
 * **Every installed app has this**, whether or not it has a page of its own —
 * there is always something a person may want to check or take back. For an app
 * whose whole purpose is a credential it opens where the member clicked rather
 * than sending them to hunt through community settings; for an app with a page it
 * is the gear beside its entry.
 *
 * What shows is scoped to what the viewer actually controls, which is not the
 * same as what they can see:
 *
 * - **Everyone** gets the two answers that are theirs — whether the app may act
 *   as them, and their own half of any connection. Nobody else's appears.
 * - **The seat** additionally gets what the community owns: the community-wide
 *   credential, where the app appears, and the governance view of what every
 *   member has given it.
 *
 * This is deliberately not the community-settings page. That one is about the
 * install — adding, renaming, turning off, removing — and belongs to admins.
 * This one is about a person's own relationship with an app that is already
 * there.
 */

import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { PluginConnectionsPanel } from "@/components/plugins/PluginConnectionsPanel";
import { PluginConsentRequests } from "@/components/plugins/PluginConsentRequests";
import { PluginMembersPanel } from "@/components/plugins/PluginMembersPanel";
import { PluginPlacementPanel } from "@/components/plugins/PluginPlacementPanel";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { useCommunities } from "@/hooks/useCommunities";
import { useCommunityPluginDetail } from "@/hooks/useCommunityPluginDetail";
import { declaredEmbeds } from "@/lib/pluginSurfaces";

export interface PluginSettingsDialogProps {
  pluginId: number;
  /** Where the app appears is an admin's to choose. */
  isCommunityAdmin: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function PluginSettingsDialog({
  pluginId,
  isCommunityAdmin,
  open,
  onOpenChange,
}: PluginSettingsDialogProps) {
  const { t } = useTranslation(["apps", "common"]);
  const { activeCommunity } = useCommunities();
  const detail = useCommunityPluginDetail(pluginId);
  const app = detail.data;

  // Placement is where the app has a page and where it may reach content, so
  // an app with either has one to choose.
  const showsPlacement =
    isCommunityAdmin &&
    !!app &&
    (declaredEmbeds(app.definition, "initiative").length > 0 ||
      (app.requested_scopes ?? []).length > 0);
  // Install management, which the seat holds — not the manifest's
  // admin-visible surfaces above, which ask whether you administer the
  // community and are a different question.
  const holdsTheSeat = Boolean(activeCommunity?.can.seat);
  const showsAdminSection = holdsTheSeat && !!app;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
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
            {/* Yours first. An app that acts as people asks everybody, admins
                included — a community admin's own name is not something their role
                answers for. */}
            {(app.consents?.length ?? 0) > 0 && (
              <section className="rounded-lg border p-4">
                <PluginConsentRequests
                  pluginId={app.id}
                  appName={app.name}
                  consents={app.consents ?? []}
                />
              </section>
            )}

            <PluginConnectionsPanel
              pluginId={app.id}
              connections={app.connections}
              canManage={holdsTheSeat}
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
                {/* Where the app goes is the community's call, and only for an app
                    that has somewhere to go. */}
                {showsPlacement && <PluginPlacementPanel app={app} />}
                <PluginMembersPanel pluginId={app.id} enabled />
              </>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
