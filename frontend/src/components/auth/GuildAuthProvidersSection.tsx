/**
 * Which of the deployment's sign-in providers this community counts as its own.
 *
 * A community does not configure a provider and does not sign anybody in —
 * whoever runs the deployment does both — so there is no issuer here, no
 * client id and no secret. What a community says is which arrivals are its
 * own, and whether they join on sight: "our Google Workspace" rather than
 * "Google".
 *
 * That first part is the narrowing. Google will vouch for anybody with a
 * Google account, so a community connecting to it says which workspace domain
 * is theirs. A community whose provider is its own identity provider needs
 * none: it already only holds their people.
 */

import { Loader2, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  ConnectableProviderRead,
  GuildProviderConnectionRead,
} from "@/api/generated/initiativeAPI.schemas";
import { ProviderMark } from "@/components/auth/ProviderMark";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
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
import { Switch } from "@/components/ui/switch";
import {
  useConnectableProviders,
  useConnectProvider,
  useDisconnectProvider,
  useGuildProviderConnections,
  useUpdateProviderConnection,
} from "@/hooks/useGuildAuthPolicy";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

/** Which claim narrows which provider. Each one spells "our tenant"
 *  differently, and only the provider knows which word it uses. */
const NARROWING_CLAIMS = ["hd", "tid", "groups", "domain"];

export const GuildAuthProvidersSection = ({ guildId }: { guildId: number }) => {
  const { t } = useTranslation("settings");
  const connectionsQuery = useGuildProviderConnections(guildId);
  const availableQuery = useConnectableProviders(guildId);
  const connect = useConnectProvider(guildId);
  const updateConnection = useUpdateProviderConnection(guildId);
  const disconnect = useDisconnectProvider(guildId);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [providerId, setProviderId] = useState("");
  const [claim, setClaim] = useState("");
  const [claimValues, setClaimValues] = useState("");
  const [autoJoin, setAutoJoin] = useState(false);
  const [removing, setRemoving] = useState<GuildProviderConnectionRead | null>(null);

  const connections = connectionsQuery.data ?? [];
  const connectedIds = new Set(connections.map((row) => row.provider_id));
  // A provider already in use is still listed by the server (that is what
  // keeps one registered for this community visible to it), so the picker
  // leaves out the ones there is nothing left to do with.
  const choosable = (availableQuery.data ?? []).filter(
    (row: ConnectableProviderRead) => !connectedIds.has(row.id)
  );

  const closeDialog = () => {
    setDialogOpen(false);
    setProviderId("");
    setClaim("");
    setClaimValues("");
    setAutoJoin(false);
  };

  const submit = () => {
    const values = claimValues
      .split(/[\s,]+/)
      .map((value) => value.trim())
      .filter(Boolean);
    connect.mutate(
      {
        provider_id: Number(providerId),
        auto_join: autoJoin,
        // Both halves or neither — the server clears a half-written one, so
        // send it the way it will store it.
        claim: claim && values.length > 0 ? claim : null,
        claim_values: claim && values.length > 0 ? values : null,
      },
      {
        onSuccess: () => {
          toast.success(t("guildAuth.connections.connected"));
          closeDialog();
        },
        onError: (error) =>
          toast.error(getErrorMessage(error, "settings:guildAuth.connections.connectError")),
      }
    );
  };

  return (
    <Card className="shadow-sm">
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle>{t("guildAuth.connections.title")}</CardTitle>
          <CardDescription>{t("guildAuth.connections.description")}</CardDescription>
        </div>
        <Button type="button" onClick={() => setDialogOpen(true)} disabled={choosable.length === 0}>
          <Plus className="h-4 w-4" />
          {t("guildAuth.connections.connect")}
        </Button>
      </CardHeader>
      <CardContent>
        {connectionsQuery.isLoading ? (
          <p className="text-muted-foreground text-sm">{t("authProviders.loading")}</p>
        ) : connections.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {choosable.length === 0
              ? t("guildAuth.connections.noneOffered")
              : t("guildAuth.connections.empty")}
          </p>
        ) : (
          <ul className="divide-y rounded-md border">
            {connections.map((row) => (
              <li key={row.id} className="flex items-center justify-between gap-4 px-3 py-3">
                <div className="flex min-w-0 items-start gap-3">
                  <ProviderMark icon={row.provider_icon} className="mt-0.5" />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{row.provider_display_name}</span>
                      {!row.enabled && (
                        <Badge variant="outline">{t("authProviders.disabledBadge")}</Badge>
                      )}
                      {!row.login_ready && (
                        <Badge variant="outline">{t("guildAuth.connections.notReady")}</Badge>
                      )}
                    </div>
                    <p className="text-muted-foreground text-sm">
                      {row.claim && row.claim_values.length > 0
                        ? t("guildAuth.connections.narrowedTo", {
                            claim: row.claim,
                            values: row.claim_values.join(", "),
                          })
                        : t("guildAuth.connections.anyoneItVouchesFor")}
                    </p>
                    {row.auto_join && (
                      <p className="text-muted-foreground text-xs">
                        {t("guildAuth.connections.joinsOnArrival")}
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <Switch
                    aria-label={t("authProviders.enabledLabel")}
                    checked={row.enabled}
                    onCheckedChange={(checked) =>
                      updateConnection.mutate(
                        { connectionId: row.id, data: { enabled: Boolean(checked) } },
                        {
                          onError: (error) =>
                            toast.error(
                              getErrorMessage(error, "settings:guildAuth.connections.connectError")
                            ),
                        }
                      )
                    }
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="text-destructive"
                    aria-label={t("guildAuth.connections.disconnect")}
                    onClick={() => setRemoving(row)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>

      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => (open ? setDialogOpen(true) : closeDialog())}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t("guildAuth.connections.dialogTitle")}</DialogTitle>
            <DialogDescription>{t("guildAuth.connections.dialogDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="connection-provider">
                {t("guildAuth.connections.providerLabel")}
              </Label>
              <Select value={providerId} onValueChange={setProviderId}>
                <SelectTrigger id="connection-provider">
                  <SelectValue placeholder={t("guildAuth.connections.providerPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {choosable.map((row) => (
                    <SelectItem key={row.id} value={String(row.id)}>
                      {row.display_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-start justify-between gap-3 rounded-md border p-3">
              <div className="space-y-1">
                <Label htmlFor="connection-auto-join">
                  {t("guildAuth.connections.autoJoinLabel")}
                </Label>
                <p className="text-muted-foreground text-xs">
                  {t("guildAuth.connections.autoJoinHelp")}
                </p>
              </div>
              <Switch
                id="connection-auto-join"
                checked={autoJoin}
                onCheckedChange={(checked) => setAutoJoin(Boolean(checked))}
              />
            </div>

            <div className="space-y-2 rounded-md border bg-muted/40 p-3">
              <Label htmlFor="connection-claim">{t("guildAuth.connections.claimLabel")}</Label>
              <p className="text-muted-foreground text-xs">
                {t("guildAuth.connections.claimHelp")}
              </p>
              <Select value={claim} onValueChange={setClaim}>
                <SelectTrigger id="connection-claim">
                  <SelectValue placeholder={t("guildAuth.connections.claimPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {NARROWING_CLAIMS.map((name) => (
                    <SelectItem key={name} value={name}>
                      {name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Input
                aria-label={t("guildAuth.connections.claimValuesLabel")}
                placeholder={t("guildAuth.connections.claimValuesPlaceholder")}
                value={claimValues}
                onChange={(event) => setClaimValues(event.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={closeDialog}>
              {t("authProviders.cancel")}
            </Button>
            <Button type="button" onClick={submit} disabled={!providerId || connect.isPending}>
              {connect.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("authProviders.saving")}
                </>
              ) : (
                t("guildAuth.connections.connect")
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
        title={t("guildAuth.connections.disconnectTitle", {
          name: removing?.provider_display_name ?? "",
        })}
        description={t("guildAuth.connections.disconnectDescription")}
        confirmLabel={t("guildAuth.connections.disconnect")}
        cancelLabel={t("authProviders.cancel")}
        destructive
        isLoading={disconnect.isPending}
        onConfirm={() => {
          if (!removing) return;
          disconnect.mutate(removing.id, {
            onSuccess: () => {
              toast.success(t("guildAuth.connections.disconnected"));
              setRemoving(null);
            },
            onError: (error) =>
              toast.error(getErrorMessage(error, "settings:guildAuth.connections.connectError")),
          });
        }}
      />
    </Card>
  );
};
