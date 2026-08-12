/**
 * Adding an app to the guild.
 *
 * Simpler than installing a dashboard, and for a reason: a dashboard belongs to
 * an initiative, so installing one is a choice of which. An app belongs to the
 * guild, so there is nothing to choose — only what to call it.
 *
 * Guild admins only. The server enforces that; this hides the action rather
 * than offering one that would be refused.
 */

import { useNavigate } from "@tanstack/react-router";
import { Download, Loader2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { MarketplaceListingDetail } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
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
import { guildAppPath, useInstallGuildApp } from "@/hooks/useGuildApps";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { useGuildPath } from "@/lib/guildUrl";
import type { DialogProps } from "@/types/dialog";

export interface InstallAppDialogProps extends DialogProps {
  listing: MarketplaceListingDetail;
}

export function InstallAppDialog({ listing, open, onOpenChange }: InstallAppDialogProps) {
  const { t } = useTranslation(["apps", "common"]);
  const navigate = useNavigate();
  const gp = useGuildPath();

  const [name, setName] = useState(listing.name);
  const install = useInstallGuildApp();

  const submit = () =>
    install.mutate(
      { listing_uid: listing.uid, name: name.trim() || listing.name },
      {
        onSuccess: (app) => {
          toast.success(t("apps:install.done", { name: app.name }));
          onOpenChange(false);
          // Straight to what it created, when it created something reachable.
          const path = guildAppPath(app);
          if (path) navigate({ to: gp(path) });
        },
        onError: (error) => {
          toast.error(getErrorMessage(error, "apps:error"));
        },
      }
    );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("apps:install.title", { name: listing.name })}</DialogTitle>
          <DialogDescription>{t("apps:install.description")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5">
          <Label htmlFor="install-app-name">{t("apps:install.name")}</Label>
          <Input
            id="install-app-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={listing.name}
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common:cancel")}
          </Button>
          <Button onClick={submit} disabled={install.isPending}>
            {install.isPending ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <Download className="mr-1.5 h-4 w-4" />
            )}
            {t("apps:install.action")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
