/**
 * "Where should this go?"
 *
 * A dashboard belongs to an initiative, so installing one is a choice of which.
 * The picker offers only the initiatives where the viewer may create dashboards
 * — the same permission the create flow uses, and the same one the server checks
 * — so the list is what the install will actually accept.
 *
 * The definition is never sent. The request names the listing; the server reads
 * what that listing publishes.
 */

import { useNavigate } from "@tanstack/react-router";
import { Download, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type MarketplaceListingDetail,
  Tool,
  Tool as ToolEnum,
} from "@/api/generated/initiativeAPI.schemas";
import { ListingProvenance } from "@/components/marketplace/ListingProvenance";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCreateDashboard } from "@/hooks/useDashboards";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { useGuildPath } from "@/lib/guildUrl";
import { toolDetailRoute } from "@/lib/tools";
import type { DialogProps } from "@/types/dialog";

export interface InstallListingDialogProps extends DialogProps {
  listing: MarketplaceListingDetail;
  /** Pre-selected when the viewer arrived from an initiative. */
  defaultInitiativeId?: number;
}

export function InstallListingDialog({
  listing,
  defaultInitiativeId,
  open,
  onOpenChange,
}: InstallListingDialogProps) {
  const { t } = useTranslation(["marketplace", "common"]);
  const navigate = useNavigate();
  const gp = useGuildPath();

  const { creatableInitiatives } = useToolCreateAccess(ToolEnum.dashboard as Tool);
  const [initiativeId, setInitiativeId] = useState<string>("");
  const [name, setName] = useState(listing.name);
  const install = useCreateDashboard();

  // Seeded once the options are known: the initiative the viewer came from when
  // they may create there, otherwise the only one they can.
  useEffect(() => {
    if (initiativeId || !creatableInitiatives.length) return;
    const fromContext = creatableInitiatives.find((i) => i.id === defaultInitiativeId);
    setInitiativeId(String((fromContext ?? creatableInitiatives[0]).id));
  }, [creatableInitiatives, defaultInitiativeId, initiativeId]);

  const submit = () => {
    if (!initiativeId) return;
    install.mutate(
      {
        name: name.trim() || listing.name,
        initiative_id: Number(initiativeId),
        listing_uid: listing.uid,
      },
      {
        onSuccess: (dashboard) => {
          toast.success(t("marketplace:install.done", { name: dashboard.name }));
          onOpenChange(false);
          navigate({
            to: gp(toolDetailRoute(Tool.dashboard, dashboard.initiative_id, dashboard.id)),
          });
        },
        onError: (error) => {
          toast.error(getErrorMessage(error, "marketplace:install.failed"));
        },
      }
    );
  };

  const nowhereToInstall = creatableInitiatives.length === 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("marketplace:install.title", { name: listing.name })}</DialogTitle>
          <DialogDescription>{t("marketplace:install.description")}</DialogDescription>
        </DialogHeader>

        {/* The last place to see who wrote this, while it is still a choice. */}
        <ListingProvenance listing={listing} />

        {nowhereToInstall ? (
          <p className="text-muted-foreground text-sm">{t("marketplace:install.noInitiatives")}</p>
        ) : (
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="install-initiative">{t("marketplace:install.initiative")}</Label>
              <Select value={initiativeId} onValueChange={setInitiativeId}>
                <SelectTrigger id="install-initiative">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {creatableInitiatives.map((initiative) => (
                    <SelectItem key={initiative.id} value={String(initiative.id)}>
                      {initiative.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="install-name">{t("marketplace:install.name")}</Label>
              <Input
                id="install-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={listing.name}
              />
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common:cancel")}
          </Button>
          <Button
            onClick={submit}
            disabled={nowhereToInstall || !initiativeId || install.isPending}
          >
            {install.isPending ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <Download className="mr-1.5 h-4 w-4" />
            )}
            {t("marketplace:install.action")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
