/**
 * An app's own settings, opened from wherever the app is.
 *
 * For an app that has no page of its own — one whose whole purpose is a
 * credential, like connecting your account at a vendor — this *is* the app. So
 * it opens where the member clicked rather than sending them to hunt through
 * guild settings for the same form.
 *
 * The form itself is the one the settings page already uses: an app's settings
 * are its connections, and one renderer draws every app's from the fields its
 * pinned definition declares.
 */

import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AppConnectionsPanel } from "@/components/apps/AppConnectionsPanel";
import { AppPlacementPanel } from "@/components/apps/AppPlacementPanel";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
            <AppConnectionsPanel
              appId={app.id}
              connections={app.connections}
              isGuildAdmin={isGuildAdmin}
            />
            {/* Where the app goes is the guild's call, so only its admins see
                the control — and only for an app that has somewhere to go. */}
            {isGuildAdmin && appEmbeds(app.definition, "initiative", ADMIN).length > 0 && (
              <AppPlacementPanel app={app} />
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
