/**
 * An app's settings, grouped by connection.
 *
 * The grouping is the point rather than a layout choice. An app does not have
 * "settings" — it has connections, each of which reaches a different system
 * with different permissions, and each of which is supplied by a different
 * person. Showing them as one flat form would hide the distinction that
 * matters:
 *
 * - A **guild connection** is one credential the whole guild uses. A guild
 *   admin fills it in; everyone else sees whether it is set, because whether an
 *   app can do its job is not a secret.
 * - A **personal connection** is each member's own account at a vendor that
 *   authorizes people rather than organizations. Every member sees their own
 *   state and only their own — the server answers per viewer, so there is
 *   nothing to filter here.
 *
 * A stored value never comes back. A secret field that already holds one shows
 * as set and renders empty, so typing into it replaces the value and leaving it
 * alone keeps it. That is why the form sends only the keys that were touched.
 *
 * One renderer draws every app's form, from the field types the pinned
 * definition declares — a new app needs no code here.
 */

import { KeyRound, Loader2, Plug, ShieldCheck, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { AppConfigValue, AppConnection, AppConnectionField } from "@/api/appConnections";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { useConnectApp, useDisconnectApp, useUpdateAppConfig } from "@/hooks/useGuildAppDetail";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { localized } from "@/lib/widgets/widgetMeta";

export interface AppConnectionsPanelProps {
  appId: number;
  connections: AppConnection[];
  isGuildAdmin: boolean;
}

export function AppConnectionsPanel({
  appId,
  connections,
  isGuildAdmin,
}: AppConnectionsPanelProps) {
  const { t } = useTranslation(["apps"]);

  if (!connections.length) {
    return <p className="text-muted-foreground text-sm">{t("apps:connections.none")}</p>;
  }

  return (
    <div className="space-y-4">
      {connections.map((connection) =>
        connection.scope === "static" ? (
          <GuildConnection
            key={connection.id}
            appId={appId}
            connection={connection}
            canManage={isGuildAdmin}
          />
        ) : (
          <PersonalConnection key={connection.id} appId={appId} connection={connection} />
        )
      )}
    </div>
  );
}

/** The shared frame: name, what it wants access to, and whether it is set. */
function ConnectionShell({
  connection,
  icon,
  scopeLabel,
  children,
}: {
  connection: AppConnection;
  icon: React.ReactNode;
  scopeLabel: string;
  children: React.ReactNode;
}) {
  const { t, i18n } = useTranslation(["apps"]);
  const name = localized(connection.label, i18n.language) ?? connection.id;
  const hint = connection.access_hint;

  return (
    <section className="space-y-3 rounded-lg border p-4">
      <header className="flex flex-wrap items-center gap-2">
        {icon}
        <h3 className="font-medium text-sm">{name}</h3>
        <Badge variant="outline">{scopeLabel}</Badge>
        {connection.satisfied ? (
          <Badge variant="secondary">{t("apps:connections.set")}</Badge>
        ) : (
          <Badge variant="outline">{t("apps:connections.notSet")}</Badge>
        )}
      </header>

      {/* Truth in advertising: the API and permissions this asks for, so an
          admin can mint the smallest credential that works. */}
      {hint?.api || hint?.scopes?.length ? (
        <p className="text-muted-foreground text-xs">
          {t("apps:connections.accessHint", {
            api: hint.api ?? "—",
            scopes: hint.scopes?.length ? hint.scopes.join(", ") : t("apps:connections.noScopes"),
          })}
        </p>
      ) : null}

      {children}
    </section>
  );
}

// --- the guild's own credential ---------------------------------------------

function GuildConnection({
  appId,
  connection,
  canManage,
}: {
  appId: number;
  connection: AppConnection;
  canManage: boolean;
}) {
  const { t } = useTranslation(["apps", "common"]);
  const [draft, setDraft] = useState<Record<string, AppConfigValue>>({});
  const save = useUpdateAppConfig(appId);
  const clear = useDisconnectApp(appId);

  // Only what was touched. A secret already stored renders empty, so sending
  // untouched keys would clear the values the admin came here to keep.
  const touched = Object.keys(draft);

  const submit = () => {
    save.mutate(
      { [connection.id]: draft },
      {
        onSuccess: () => {
          setDraft({});
          toast.success(t("apps:connections.saved"));
        },
        onError: (error) => toast.error(getErrorMessage(error, "apps:error")),
      }
    );
  };

  return (
    <ConnectionShell
      connection={connection}
      icon={<KeyRound className="h-4 w-4 text-muted-foreground" aria-hidden />}
      scopeLabel={t("apps:connections.guildScope")}
    >
      {canManage ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            {connection.fields
              .filter((field) => !field.managed)
              .map((field) => (
                <ConnectionFieldInput
                  key={field.key}
                  field={field}
                  connection={connection}
                  value={draft[field.key]}
                  onChange={(value) => setDraft((prev) => ({ ...prev, [field.key]: value }))}
                />
              ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={submit} disabled={!touched.length || save.isPending}>
              {save.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
              {t("common:save")}
            </Button>
            {connection.satisfied && (
              <Button
                size="sm"
                variant="outline"
                disabled={clear.isPending}
                onClick={() =>
                  clear.mutate(connection.id, {
                    onSuccess: () => toast.success(t("apps:connections.cleared")),
                    onError: (error) => toast.error(getErrorMessage(error, "apps:error")),
                  })
                }
              >
                {t("apps:connections.clear")}
              </Button>
            )}
          </div>
        </>
      ) : (
        // Not a secret, and useful: a member seeing a widget sit dark should be
        // able to tell whether an admin still has something to fill in.
        <p className="text-muted-foreground text-sm">
          {connection.satisfied
            ? t("apps:connections.memberSet")
            : t("apps:connections.memberNotSet")}
        </p>
      )}
    </ConnectionShell>
  );
}

/** One input, drawn from the field type the pinned definition declares. */
function ConnectionFieldInput({
  field,
  connection,
  value,
  onChange,
}: {
  field: AppConnectionField;
  connection: AppConnection;
  value: AppConfigValue;
  onChange: (value: AppConfigValue) => void;
}) {
  const { t, i18n } = useTranslation(["apps"]);
  const label = localized(field.label, i18n.language) ?? field.key;
  const isSet = connection.has_value[field.key] === true;
  const stored = connection.values[field.key];
  const id = `${connection.id}-${field.key}`;

  if (field.type === "bool") {
    const current = typeof value === "boolean" ? value : stored === true;
    return (
      <div className="flex items-center gap-2">
        <Switch id={id} checked={current} onCheckedChange={onChange} />
        <Label htmlFor={id}>{label}</Label>
      </div>
    );
  }

  if (field.type === "select") {
    const current = typeof value === "string" ? value : (stored as string | undefined);
    return (
      <div className="space-y-1.5">
        <Label htmlFor={id}>{label}</Label>
        <Select value={current ?? ""} onValueChange={onChange}>
          <SelectTrigger id={id}>
            <SelectValue placeholder={t("apps:connections.choose")} />
          </SelectTrigger>
          <SelectContent>
            {(field.options ?? []).map((option) => (
              <SelectItem key={option} value={option}>
                {option}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    );
  }

  const isSecret = field.type === "secret";
  const current =
    typeof value === "string" || typeof value === "number"
      ? String(value)
      : isSecret
        ? ""
        : ((stored as string | number | undefined) ?? "");

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>
        {label}
        {field.required && <span aria-hidden> *</span>}
      </Label>
      <Input
        id={id}
        // A stored secret is never sent back, so the field starts empty and
        // says it is already set instead. Typing replaces it; leaving it alone
        // keeps it.
        type={isSecret ? "password" : field.type === "int" ? "number" : "text"}
        autoComplete={isSecret ? "new-password" : "off"}
        placeholder={
          isSecret && isSet ? t("apps:connections.secretSet") : t("apps:connections.empty")
        }
        value={String(current)}
        onChange={(event) =>
          onChange(
            field.type === "int"
              ? event.target.value === ""
                ? null
                : Number(event.target.value)
              : event.target.value
          )
        }
      />
    </div>
  );
}

// --- a member's own account --------------------------------------------------

function PersonalConnection({ appId, connection }: { appId: number; connection: AppConnection }) {
  const { t } = useTranslation(["apps", "common"]);
  const connect = useConnectApp(appId);
  const disconnect = useDisconnectApp(appId);

  const start = () =>
    connect.mutate(connection.id, {
      onSuccess: (started) => {
        // The vendor's flow runs at the app's own URL, which the server
        // assembles from the deployment's registration — the client never
        // builds that address and never needs to know it. A new tab rather
        // than a redirect, so the member comes back to where they were, and
        // `noopener` keeps the app's page from reaching into this one.
        if (started.connect_url) {
          window.open(started.connect_url, "_blank", "noopener,noreferrer");
          toast.success(t("apps:connections.connectOpened"));
          return;
        }
        // Nowhere to send them: this deployment has no live registration for
        // the app. The connection row and its handle still exist, which is why
        // this is a message rather than a failure.
        toast.error(t("apps:connections.connectUnavailable"));
      },
      onError: (error) => toast.error(getErrorMessage(error, "apps:error")),
    });

  return (
    <ConnectionShell
      connection={connection}
      icon={<Plug className="h-4 w-4 text-muted-foreground" aria-hidden />}
      scopeLabel={t("apps:connections.personalScope")}
    >
      <p className="text-muted-foreground text-sm">{t("apps:connections.personalExplainer")}</p>

      {connection.blocked ? (
        <p className="flex items-center gap-2 text-destructive text-sm">
          <TriangleAlert className="h-4 w-4" aria-hidden />
          {t("apps:connections.blocked")}
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {connection.status ? (
            <span className="flex items-center gap-1.5 text-sm">
              <ShieldCheck className="h-4 w-4 text-muted-foreground" aria-hidden />
              {connection.account_label
                ? t("apps:connections.connectedAs", { account: connection.account_label })
                : t(`apps:connections.status.${connection.status}`, {
                    defaultValue: connection.status,
                  })}
            </span>
          ) : null}

          <Button size="sm" onClick={start} disabled={connect.isPending}>
            {connect.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            {connection.status ? t("apps:connections.reconnect") : t("apps:connections.connect")}
          </Button>

          {connection.status && (
            <Button
              size="sm"
              variant="outline"
              disabled={disconnect.isPending}
              onClick={() =>
                disconnect.mutate(connection.id, {
                  onSuccess: () => toast.success(t("apps:connections.disconnected")),
                  onError: (error) => toast.error(getErrorMessage(error, "apps:error")),
                })
              }
            >
              {t("apps:connections.disconnect")}
            </Button>
          )}
        </div>
      )}
    </ConnectionShell>
  );
}
