/**
 * Whether this app may act as you, and how deeply.
 *
 * A guild admin adding an app is one decision; the app making requests that
 * carry *your* name is a second one, and this is where the second is made. The
 * panel is the member's own — it takes no user id and shows nobody else's
 * answer, because there is no version of this question an admin answers on
 * somebody's behalf.
 *
 * Two levels rather than one switch: authorizing at all is what lets the app
 * read as you, and writing is asked for separately because it is a different
 * thing to agree to. Withdrawing takes effect on the app's very next request.
 *
 * It draws only for an app that actually acts as people. Whether it does is
 * the operator's grant on the registration, not something the install claims,
 * so an app that loses the grant stops asking.
 */

import { ShieldCheck, ShieldOff, UserRoundCheck } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { AppDelegation } from "@/api/appConnections";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useGrantAppDelegation, useRevokeAppDelegation } from "@/hooks/useGuildAppDetail";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

export interface AppDelegationPanelProps {
  appId: number;
  appName: string;
  delegation: AppDelegation | null | undefined;
}

export function AppDelegationPanel({ appId, appName, delegation }: AppDelegationPanelProps) {
  const { t } = useTranslation(["apps", "common"]);
  const grant = useGrantAppDelegation(appId);
  const revoke = useRevokeAppDelegation(appId);

  const granted = delegation?.granted ?? false;
  const canWrite = delegation?.can_write ?? false;
  const busy = grant.isPending || revoke.isPending;

  const authorize = async (canWriteNext: boolean) => {
    try {
      await grant.mutateAsync(canWriteNext);
      toast.success(t("apps:delegation.authorized", { name: appName }));
    } catch (error) {
      toast.error(getErrorMessage(error, "apps:delegation.failed"));
    }
  };

  const withdraw = async () => {
    try {
      await revoke.mutateAsync();
      toast.success(t("apps:delegation.withdrawn", { name: appName }));
    } catch (error) {
      toast.error(getErrorMessage(error, "apps:delegation.failed"));
    }
  };

  return (
    <section className="space-y-3 rounded-lg border p-4">
      <header className="flex items-start gap-3">
        <UserRoundCheck className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" aria-hidden />
        <div className="flex-1 space-y-1">
          <div className="flex items-center gap-2">
            <h3 className="font-medium text-sm">{t("apps:delegation.title")}</h3>
            {granted ? (
              <Badge variant="secondary" className="gap-1">
                <ShieldCheck className="h-3 w-3" aria-hidden />
                {canWrite ? t("apps:delegation.levelWrite") : t("apps:delegation.levelRead")}
              </Badge>
            ) : (
              <Badge variant="outline" className="gap-1">
                <ShieldOff className="h-3 w-3" aria-hidden />
                {t("apps:delegation.levelNone")}
              </Badge>
            )}
          </div>
          <p className="text-muted-foreground text-sm">
            {t("apps:delegation.description", { name: appName })}
          </p>
        </div>
      </header>

      {granted ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-4">
            <div className="space-y-0.5">
              <Label htmlFor={`delegation-write-${appId}`} className="text-sm">
                {t("apps:delegation.writeLabel")}
              </Label>
              <p className="text-muted-foreground text-xs">
                {t("apps:delegation.writeHint", { name: appName })}
              </p>
            </div>
            <Switch
              id={`delegation-write-${appId}`}
              checked={canWrite}
              disabled={busy}
              onCheckedChange={(next) => authorize(next)}
            />
          </div>

          {delegation?.granted_at && (
            <p className="text-muted-foreground text-xs">
              {t("apps:delegation.since", {
                date: new Date(delegation.granted_at).toLocaleDateString(),
              })}
            </p>
          )}

          <Button variant="outline" size="sm" disabled={busy} onClick={withdraw}>
            {t("apps:delegation.withdraw")}
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          {delegation?.revoked_at && (
            <p className="text-muted-foreground text-xs">
              {t("apps:delegation.stoppedOn", {
                date: new Date(delegation.revoked_at).toLocaleDateString(),
              })}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button size="sm" disabled={busy} onClick={() => authorize(false)}>
              {t("apps:delegation.allowRead")}
            </Button>
            <Button variant="outline" size="sm" disabled={busy} onClick={() => authorize(true)}>
              {t("apps:delegation.allowWrite")}
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
