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
 * A version that asks for more than the install holds — a new scope, or a new
 * surface inside initiatives — is not applied on its own. The server says what
 * it asks for in `pending_update`, and the panel shows that as "Version X wants
 * to: …" with accept and decline. Accepting grants the new scopes with the
 * version; declining keeps the current version and stops the asking until a
 * newer one is published.
 *
 * Guild admins only — the caller decides that, since this renders inside a
 * section that has already made the call.
 */

import { isAxiosError } from "axios";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { GuildAppDetail, GuildAppUpgradeAsks } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useDeclineAppUpgrade, useUpgradeApp } from "@/hooks/useGuildAppDetail";
import { useUpdateGuildApp } from "@/hooks/useGuildApps";
import { type AppNames, scopeSentence } from "@/lib/appScopes";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { localized } from "@/lib/widgets/widgetMeta";

export function AppUpdatesPanel({ app }: { app: GuildAppDetail }) {
  const { t } = useTranslation(["apps", "common"]);
  const update = useUpdateGuildApp(app.id);
  const upgrade = useUpgradeApp(app.id);
  const pending = app.update_version ?? null;
  const asks = app.pending_update ?? null;

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
        {asks ? null : pending ? (
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

      {asks && <PendingUpdate appId={app.id} asks={asks} appNames={app.app_names} />}
    </section>
  );
}

/** "Version X wants to: …", with the seat's accept and decline. */
function PendingUpdate({
  appId,
  asks,
  appNames,
}: {
  appId: number;
  asks: GuildAppUpgradeAsks;
  appNames?: AppNames;
}) {
  const { t, i18n } = useTranslation(["apps", "common", "nav"]);
  const upgrade = useUpgradeApp(appId);
  const decline = useDeclineAppUpgrade(appId);
  const busy = upgrade.isPending || decline.isPending;

  /** A refusal because the offer moved says so; the panel then refreshes. */
  const failed = (error: unknown) => {
    const moved = isAxiosError(error) && error.response?.status === 409;
    toast.error(moved ? t("apps:updates.moved") : getErrorMessage(error, "apps:error"));
  };

  const accept = () =>
    upgrade.mutate(
      { version: asks.version, add_scopes: asks.added_scopes },
      {
        onSuccess: (updated) =>
          toast.success(t("apps:manage.upgraded", { version: updated.listing_version })),
        onError: failed,
      }
    );

  const refuse = () =>
    decline.mutate(asks.version, {
      onSuccess: () => toast.success(t("apps:updates.declinedDone", { version: asks.version })),
      onError: failed,
    });

  return (
    <div className="space-y-2 rounded-md border p-3">
      <p className="font-medium text-sm">{t("apps:updates.wants", { version: asks.version })}</p>
      <ul className="list-disc space-y-1 pl-5 text-sm">
        {asks.added_scopes.map((scope) => (
          <li key={scope}>{scopeSentence(scope, t, appNames)}</li>
        ))}
        {asks.added_surfaces.map((surface) => (
          <li key={surface.id}>
            {t("apps:updates.newSurface", {
              name: localized(surface.name, i18n.language) ?? surface.id,
            })}
          </li>
        ))}
      </ul>
      {asks.declined && (
        <p className="text-muted-foreground text-xs">
          {t("apps:updates.declined", { version: asks.version })}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={busy} onClick={accept}>
          {upgrade.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
          {t("apps:updates.accept")}
        </Button>
        {!asks.declined && (
          <Button size="sm" variant="outline" disabled={busy} onClick={refuse}>
            {decline.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            {t("apps:updates.decline")}
          </Button>
        )}
      </div>
    </div>
  );
}
