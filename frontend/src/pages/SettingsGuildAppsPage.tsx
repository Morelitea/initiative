/**
 * Managing the guild's apps.
 *
 * The sidebar shows what is *on*; this is where an admin turns one off, renames
 * it, or removes it — so disabled apps appear here and nowhere else, otherwise
 * turning one off would hide the switch that turns it back on.
 *
 * Removing an app trashes what it created rather than deleting it, and the
 * confirmation says so: the events a guild put in a calendar should not feel
 * like collateral.
 */

import { Link } from "@tanstack/react-router";
import { Blocks, Loader2, Store } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { GuildAppRead } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useGuildApps, useUninstallGuildApp, useUpdateGuildApp } from "@/hooks/useGuildApps";
import { useGuilds } from "@/hooks/useGuilds";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { useGuildPath } from "@/lib/guildUrl";

export function SettingsGuildAppsPage() {
  const { t } = useTranslation(["apps", "common"]);
  const gp = useGuildPath();
  const appsQuery = useGuildApps();
  const { activeGuild } = useGuilds();
  const isGuildAdmin = activeGuild?.role === "admin";

  const apps = appsQuery.data?.items ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("apps:manage.title")}</CardTitle>
        <CardDescription>{t("apps:manage.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {appsQuery.isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : apps.length ? (
          apps.map((app) => <AppRow key={app.id} app={app} canManage={Boolean(isGuildAdmin)} />)
        ) : (
          <div className="space-y-3 rounded-lg border border-dashed p-6 text-center">
            <p className="text-muted-foreground text-sm">{t("apps:manage.empty")}</p>
            {isGuildAdmin && (
              <Button variant="outline" asChild>
                <Link to={gp("/marketplace")} search={{ kind: "app" }}>
                  <Store className="mr-1.5 h-4 w-4" />
                  {t("apps:manage.browse")}
                </Link>
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function AppRow({ app, canManage }: { app: GuildAppRead; canManage: boolean }) {
  const { t } = useTranslation(["apps", "common"]);
  const [name, setName] = useState(app.name);
  const [confirming, setConfirming] = useState(false);
  const update = useUpdateGuildApp(app.id);
  const uninstall = useUninstallGuildApp();

  const save = (patch: { name?: string; enabled?: boolean }) =>
    update.mutate(patch, {
      onSuccess: () => toast.success(t("apps:manage.saved")),
      onError: (error) => toast.error(getErrorMessage(error, "apps:error")),
    });

  const remove = () =>
    uninstall.mutate(app.id, {
      onSuccess: () => {
        toast.success(t("apps:manage.removed", { name: app.name }));
        setConfirming(false);
      },
      onError: (error) => toast.error(getErrorMessage(error, "apps:error")),
    });

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border p-3">
      <Blocks className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden />
      <div className="min-w-0 flex-1 space-y-1">
        {canManage ? (
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            onBlur={() => name.trim() && name !== app.name && save({ name: name.trim() })}
            aria-label={t("apps:manage.rename")}
            className="h-8 max-w-xs"
          />
        ) : (
          <p className="font-medium text-sm">{app.name}</p>
        )}
        <p className="text-muted-foreground text-xs">
          {t("apps:manage.installed", {
            date: new Date(app.created_at).toLocaleDateString(),
          })}
        </p>
      </div>

      {!app.enabled && <Badge variant="outline">{t("apps:manage.disabled")}</Badge>}

      {canManage && (
        <div className="flex shrink-0 items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => save({ enabled: !app.enabled })}
            disabled={update.isPending}
          >
            {update.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            {app.enabled ? t("apps:manage.disable") : t("apps:manage.enable")}
          </Button>
          <Button size="sm" variant="destructive" onClick={() => setConfirming(true)}>
            {t("apps:manage.remove")}
          </Button>
        </div>
      )}

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("apps:manage.removeTitle", { name: app.name })}
        description={t("apps:manage.removeBody")}
        confirmLabel={t("apps:manage.remove")}
        onConfirm={remove}
        isLoading={uninstall.isPending}
        destructive
      />
    </div>
  );
}
