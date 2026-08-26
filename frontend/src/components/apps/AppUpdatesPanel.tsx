/**
 * How one install takes new versions, and the button for when it does not.
 *
 * Automatic is where an install starts, so the switch here is the way *out* of
 * it rather than something to find and turn on. Turned off, the guild reads
 * each version first and applies it with the button beside it — the same re-pin
 * the server's sweep would have done, asked for by hand.
 *
 * The button appears only when there is a version to move to, which the server
 * answers with `update_version`. An install already on the newest gets a plain
 * "Up to date" rather than a button whose only outcome is being told there was
 * nothing to do.
 *
 * Guild admins only — the caller decides that, since this renders inside a
 * section that has already made the call.
 */

import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { GuildAppDetail } from "@/api/appConnections";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useUpgradeApp } from "@/hooks/useGuildAppDetail";
import { useUpdateGuildApp } from "@/hooks/useGuildApps";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

export function AppUpdatesPanel({ app }: { app: GuildAppDetail }) {
  const { t } = useTranslation(["apps", "common"]);
  const update = useUpdateGuildApp(app.id);
  const upgrade = useUpgradeApp(app.id);
  const pending = app.update_version ?? null;

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-4">
        <div className="space-y-0.5">
          <p className="font-medium text-sm">{t("apps:manage.autoUpdate")}</p>
          <p className="text-muted-foreground text-xs">{t("apps:manage.autoUpdateHelp")}</p>
        </div>
        <Switch
          aria-label={t("apps:manage.autoUpdate")}
          checked={app.auto_update}
          disabled={update.isPending}
          onCheckedChange={(checked) =>
            update.mutate(
              { auto_update: checked },
              {
                onSuccess: () =>
                  toast.success(
                    checked ? t("apps:manage.autoUpdateOn") : t("apps:manage.autoUpdateOff")
                  ),
                onError: (error) => toast.error(getErrorMessage(error, "apps:error")),
              }
            )
          }
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted-foreground text-xs">
          {t("apps:manage.version", { version: app.listing_version })}
        </span>
        {pending ? (
          <Button
            size="sm"
            variant="outline"
            disabled={upgrade.isPending}
            onClick={() =>
              upgrade.mutate(undefined, {
                onSuccess: (updated) =>
                  toast.success(t("apps:manage.upgraded", { version: updated.listing_version })),
                onError: (error) => toast.error(getErrorMessage(error, "apps:error")),
              })
            }
          >
            {upgrade.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            {t("apps:manage.upgradeTo", { version: pending })}
          </Button>
        ) : (
          <span className="text-muted-foreground text-xs">{t("apps:manage.upToDate")}</span>
        )}
      </div>
    </section>
  );
}
