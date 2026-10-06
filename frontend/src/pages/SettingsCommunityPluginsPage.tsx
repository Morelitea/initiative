/**
 * Managing the community's plug-ins.
 *
 * The sidebar shows what is *on*; this is where an admin turns one off, renames
 * it, or removes it — so disabled plug-ins appear here and nowhere else, otherwise
 * turning one off would hide the switch that turns it back on.
 *
 * Removing a plug-in trashes what it created rather than deleting it — and ends
 * every credential it held, the community's and each member's. The confirmation
 * says both: the events a community put in a calendar should not feel like
 * collateral, and nobody should be surprised that access at the vendor stopped.
 *
 * Some plug-ins come with the platform rather than being chosen here. They appear
 * like any other — visible, configurable, renameable — with no switch and no
 * remove button, because whether they exist is the operator's decision rather
 * than the community's. The affordances are absent instead of present-and-refusing.
 *
 * Expanding a row opens what that plug-in actually needs — its connections, grouped
 * — and, for an admin, who has connected to it. Both live behind the expander
 * rather than on the row, because most visits here are to rename or turn
 * something off.
 *
 * That is also where a plug-in's update cadence lives. An install takes new
 * versions on its own unless a community admin turns that off here, after which the
 * Update button beside it is how they land.
 */

import { Link } from "@tanstack/react-router";
import { Blocks, ChevronDown, Loader2, ShieldCheck, Store, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ListingKind } from "@/api/generated/initiativeAPI.schemas";
import { PluginConnectionsPanel } from "@/components/plugins/PluginConnectionsPanel";
import { PluginMembersPanel } from "@/components/plugins/PluginMembersPanel";
import { PluginPlacementPanel } from "@/components/plugins/PluginPlacementPanel";
import { PluginScopesPanel } from "@/components/plugins/PluginScopesPanel";
import { PluginUpdatesPanel } from "@/components/plugins/PluginUpdatesPanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useCommunities } from "@/hooks/useCommunities";
import { useCommunityPluginDetail } from "@/hooks/useCommunityPluginDetail";
import {
  useCommunityPlugins,
  useUninstallCommunityPlugin,
  useUpdateCommunityPlugin,
} from "@/hooks/useCommunityPlugins";
import { useCommunityPath } from "@/lib/communityUrl";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { declaredEmbeds } from "@/lib/pluginSurfaces";
import { cn } from "@/lib/utils";

export function SettingsCommunityPluginsPage() {
  const { t } = useTranslation(["plugins", "common"]);
  const gp = useCommunityPath();
  const pluginsQuery = useCommunityPlugins();
  const { activeCommunity } = useCommunities();
  // Installing a plug-in, and the credentials that authorize the whole
  // community, are the seat's. Connecting your own account is not, and
  // happens from the plug-in itself rather than here.
  const holdsTheSeat = Boolean(activeCommunity?.can.seat);

  const plugins = pluginsQuery.data?.items ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("plugins:manage.title")}</CardTitle>
        <CardDescription>{t("plugins:manage.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {pluginsQuery.isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : plugins.length ? (
          plugins.map((plugin) => (
            <PluginRow key={plugin.id} plugin={plugin} canManage={Boolean(holdsTheSeat)} />
          ))
        ) : (
          <div className="space-y-3 rounded-lg border border-dashed p-6 text-center">
            <p className="text-muted-foreground text-sm">{t("plugins:manage.empty")}</p>
            {holdsTheSeat && (
              <Button variant="outline" asChild>
                <Link to={gp("/marketplace")} search={{ kind: ListingKind.plugin }}>
                  <Store className="mr-1.5 h-4 w-4" />
                  {t("plugins:manage.browse")}
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
export interface PluginListItem {
  id: number;
  name: string;
  enabled: boolean;
  created_at: string;
  needs_config?: boolean;
  config_state?: string;
  config_state_detail?: string | null;
  /** Provided by the platform: named as such, and not removable here. */
  mandatory?: boolean;
  /** False when the plug-in's service is not set up on this server. */
  available?: boolean;
}

function PluginRow({ plugin, canManage }: { plugin: PluginListItem; canManage: boolean }) {
  const { t } = useTranslation(["plugins", "common"]);
  const [name, setName] = useState(plugin.name);
  const [confirming, setConfirming] = useState(false);
  const [open, setOpen] = useState(false);
  const update = useUpdateCommunityPlugin(plugin.id);
  const uninstall = useUninstallCommunityPlugin();

  const save = (patch: { name?: string; enabled?: boolean }) =>
    update.mutate(patch, {
      onSuccess: () => toast.success(t("plugins:manage.saved")),
      onError: (error) => toast.error(getErrorMessage(error, "plugins:error")),
    });

  const remove = () =>
    uninstall.mutate(plugin.id, {
      onSuccess: () => {
        toast.success(t("plugins:manage.removed", { name: plugin.name }));
        setConfirming(false);
      },
      onError: (error) => toast.error(getErrorMessage(error, "plugins:error")),
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
              onBlur={() => name.trim() && name !== plugin.name && save({ name: name.trim() })}
              aria-label={t("plugins:manage.rename")}
              className="h-8 max-w-xs"
            />
          ) : (
            <p className="font-medium text-sm">{plugin.name}</p>
          )}
          <p className="text-muted-foreground text-xs">
            {t("plugins:manage.installed", {
              date: new Date(plugin.created_at).toLocaleDateString(),
            })}
          </p>
        </div>

        {/* Unfinished configuration is the one thing worth surfacing on the
            collapsed row: it is why a plug-in looks installed and does nothing. */}
        {plugin.needs_config && (
          <Badge variant="outline" className="gap-1">
            <TriangleAlert className="h-3 w-3" aria-hidden />
            {t("plugins:manage.needsConfig")}
          </Badge>
        )}
        {plugin.config_state === "invalid" && (
          <Badge variant="destructive">
            {plugin.config_state_detail ?? t("plugins:manage.configInvalid")}
          </Badge>
        )}
        {/* Visible, so nobody wonders what it is — just not removable. */}
        {plugin.mandatory && (
          <Badge variant="secondary" className="gap-1">
            <ShieldCheck className="h-3 w-3" aria-hidden />
            {t("plugins:manage.provided")}
          </Badge>
        )}
        {plugin.available === false && (
          <Badge variant="outline">{t("plugins:manage.unavailable")}</Badge>
        )}
        {!plugin.enabled && <Badge variant="outline">{t("plugins:manage.disabled")}</Badge>}

        <div className="flex shrink-0 items-center gap-2">
          {/* A plug-in the platform provides has no switch and no remove button:
              the affordances are absent rather than present-and-refusing. */}
          {canManage && !plugin.mandatory && (
            <>
              <Button
                size="sm"
                variant="outline"
                onClick={() => save({ enabled: !plugin.enabled })}
                disabled={update.isPending}
              >
                {update.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
                {plugin.enabled ? t("plugins:manage.disable") : t("plugins:manage.enable")}
              </Button>
              <Button size="sm" variant="destructive" onClick={() => setConfirming(true)}>
                {t("plugins:manage.remove")}
              </Button>
            </>
          )}
          <CollapsibleTrigger asChild>
            <Button size="sm" variant="ghost" aria-label={t("plugins:manage.configure")}>
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
        {open && <PluginDetailPanels pluginId={plugin.id} canManage={canManage} />}
      </CollapsibleContent>

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("plugins:manage.removeTitle", { name: plugin.name })}
        description={t("plugins:manage.removeBody")}
        confirmLabel={t("plugins:manage.remove")}
        onConfirm={remove}
        isLoading={uninstall.isPending}
        destructive
      />
    </Collapsible>
  );
}

/**
 * The plug-in's connections, and — for the seat — where it appears and who opens
 * it there, what it can reach, who has connected to it and how it takes new
 * versions.
 */
function PluginDetailPanels({ pluginId, canManage }: { pluginId: number; canManage: boolean }) {
  const { t } = useTranslation(["plugins", "common"]);
  const detail = useCommunityPluginDetail(pluginId);

  if (detail.isLoading) return <Skeleton className="m-3 h-24" />;
  if (!detail.data) return null;

  return (
    <div className="space-y-6 border-t p-4">
      <PluginConnectionsPanel
        pluginId={pluginId}
        connections={detail.data.connections}
        canManage={canManage}
      />

      {canManage && (
        <>
          {/* Only a plug-in with an initiative surface has somewhere to place. */}
          {declaredEmbeds(detail.data.definition, "initiative").length > 0 && (
            <PluginPlacementPanel plugin={detail.data} />
          )}

          {(detail.data.requested_scopes ?? []).length > 0 && (
            <PluginScopesPanel plugin={detail.data} />
          )}

          <section className="space-y-2">
            <h3 className="font-medium text-sm">{t("plugins:members.title")}</h3>
            <PluginMembersPanel pluginId={pluginId} enabled={canManage} />
          </section>

          <PluginUpdatesPanel plugin={detail.data} />
        </>
      )}
    </div>
  );
}
