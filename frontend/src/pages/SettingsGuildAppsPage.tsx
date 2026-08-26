/**
 * Managing the guild's apps.
 *
 * The sidebar shows what is *on*; this is where an admin turns one off, renames
 * it, or removes it — so disabled apps appear here and nowhere else, otherwise
 * turning one off would hide the switch that turns it back on.
 *
 * Removing an app trashes what it created rather than deleting it — and ends
 * every credential it held, the guild's and each member's. The confirmation
 * says both: the events a guild put in a calendar should not feel like
 * collateral, and nobody should be surprised that access at the vendor stopped.
 *
 * Some apps come with the platform rather than being chosen here. They appear
 * like any other — visible, configurable, renameable — with no switch and no
 * remove button, because whether they exist is the operator's decision rather
 * than the guild's. The affordances are absent instead of present-and-refusing.
 *
 * Expanding a row opens what that app actually needs — its connections, grouped
 * — and, for an admin, who has connected to it. Both live behind the expander
 * rather than on the row, because most visits here are to rename or turn
 * something off.
 *
 * That is also where an app's update cadence lives. An install takes new
 * versions on its own unless a guild admin turns that off here, after which the
 * Update button beside it is how they land.
 */

import { Link } from "@tanstack/react-router";
import { Blocks, ChevronDown, Loader2, ShieldCheck, Store, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { AppConnectionsPanel } from "@/components/apps/AppConnectionsPanel";
import { AppMembersPanel } from "@/components/apps/AppMembersPanel";
import { AppUpdatesPanel } from "@/components/apps/AppUpdatesPanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useGuildAppDetail } from "@/hooks/useGuildAppDetail";
import { useGuildApps, useUninstallGuildApp, useUpdateGuildApp } from "@/hooks/useGuildApps";
import { useGuilds } from "@/hooks/useGuilds";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { useGuildPath } from "@/lib/guildUrl";
import { cn } from "@/lib/utils";

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

/**
 * What this page reads off an install.
 *
 * Stated structurally rather than as the generated read: the configuration
 * fields are optional here, so the page is correct whether or not an install
 * reports them, and one row type serves both the list payload and the detail.
 */
export interface AppListItem {
  id: number;
  name: string;
  enabled: boolean;
  created_at: string;
  needs_config?: boolean;
  config_state?: string;
  config_state_detail?: string | null;
  /** Provided by the platform: named as such, and not removable here. */
  mandatory?: boolean;
  /** False when the app's service is not set up on this server. */
  available?: boolean;
}

function AppRow({ app, canManage }: { app: AppListItem; canManage: boolean }) {
  const { t } = useTranslation(["apps", "common"]);
  const [name, setName] = useState(app.name);
  const [confirming, setConfirming] = useState(false);
  const [open, setOpen] = useState(false);
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
    <Collapsible open={open} onOpenChange={setOpen} className="rounded-lg border">
      <div className="flex flex-wrap items-center gap-3 p-3">
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

        {/* Unfinished configuration is the one thing worth surfacing on the
            collapsed row: it is why an app looks installed and does nothing. */}
        {app.needs_config && (
          <Badge variant="outline" className="gap-1">
            <TriangleAlert className="h-3 w-3" aria-hidden />
            {t("apps:manage.needsConfig")}
          </Badge>
        )}
        {app.config_state === "invalid" && (
          <Badge variant="destructive">
            {app.config_state_detail ?? t("apps:manage.configInvalid")}
          </Badge>
        )}
        {/* Visible, so nobody wonders what it is — just not removable. */}
        {app.mandatory && (
          <Badge variant="secondary" className="gap-1">
            <ShieldCheck className="h-3 w-3" aria-hidden />
            {t("apps:manage.provided")}
          </Badge>
        )}
        {app.available === false && <Badge variant="outline">{t("apps:manage.unavailable")}</Badge>}
        {!app.enabled && <Badge variant="outline">{t("apps:manage.disabled")}</Badge>}

        <div className="flex shrink-0 items-center gap-2">
          {/* An app the platform provides has no switch and no remove button:
              the affordances are absent rather than present-and-refusing. */}
          {canManage && !app.mandatory && (
            <>
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
            </>
          )}
          <CollapsibleTrigger asChild>
            <Button size="sm" variant="ghost" aria-label={t("apps:manage.configure")}>
              <ChevronDown
                className={cn("h-4 w-4 transition-transform", !open && "-rotate-90")}
                aria-hidden
              />
            </Button>
          </CollapsibleTrigger>
        </div>
      </div>

      <CollapsibleContent>
        {/* Fetched only once opened: the detail read carries every connection's
            whole pinned form, which the collapsed list has no use for. */}
        {open && <AppDetailPanels appId={app.id} canManage={canManage} />}
      </CollapsibleContent>

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
    </Collapsible>
  );
}

/**
 * The app's connections, and — for an admin — who has connected to it and how
 * it takes new versions.
 */
function AppDetailPanels({ appId, canManage }: { appId: number; canManage: boolean }) {
  const { t } = useTranslation(["apps", "common"]);
  const detail = useGuildAppDetail(appId);

  if (detail.isLoading) return <Skeleton className="m-3 h-24" />;
  if (!detail.data) return null;

  return (
    <div className="space-y-6 border-t p-4">
      <AppConnectionsPanel
        appId={appId}
        connections={detail.data.connections}
        isGuildAdmin={canManage}
      />

      {canManage && (
        <>
          <section className="space-y-2">
            <h3 className="font-medium text-sm">{t("apps:members.title")}</h3>
            <AppMembersPanel appId={appId} enabled={canManage} />
          </section>

          <AppUpdatesPanel app={detail.data} />
        </>
      )}
    </div>
  );
}
