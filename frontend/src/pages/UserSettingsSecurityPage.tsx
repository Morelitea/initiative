import { FormEvent, useMemo, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Smartphone, Trash2 } from "lucide-react";

import {
  useMyApiKeys,
  useDeviceTokens,
  useCreateApiKey,
  useDeleteApiKey,
  useRevokeDeviceToken,
} from "@/hooks/useSecurity";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import type { ApiKeyMetadata, DeviceTokenInfo } from "@/api/generated/initiativeAPI.schemas";
import { Input } from "@/components/ui/input";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

const formatDateTime = (value?: string | null) => {
  if (!value) {
    return "—";
  }
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(value));
  } catch {
    return value;
  }
};

const computeStatus = (key: ApiKeyMetadata) => {
  if (!key.is_active) {
    return { labelKey: "security.statusDisabled" as const, variant: "destructive" as const };
  }
  if (key.expires_at && new Date(key.expires_at).getTime() <= Date.now()) {
    return { labelKey: "security.statusExpired" as const, variant: "secondary" as const };
  }
  return { labelKey: "security.statusActive" as const, variant: "default" as const };
};

export const UserSettingsSecurityPage = () => {
  const { t } = useTranslation("settings");
  const [name, setName] = useState("");
  const [expiresAtInput, setExpiresAtInput] = useState("");
  const [generatedSecret, setGeneratedSecret] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<DeviceTokenInfo | null>(null);

  // API Keys queries and mutations
  const apiKeysQuery = useMyApiKeys();

  const createKey = useCreateApiKey({
    onSuccess: (data) => {
      toast.success(t("security.createSuccess"));
      setGeneratedSecret(data.secret);
      setName("");
      setExpiresAtInput("");
    },
    onError: () => {
      toast.error(t("security.createError"));
    },
  });

  const deleteKey = useDeleteApiKey({
    onMutate: (keyId: number) => {
      setDeleteTarget(keyId);
    },
    onSuccess: () => {
      toast.success(t("security.deleteSuccess"));
    },
    onError: () => {
      toast.error(t("security.deleteError"));
    },
    onSettled: () => {
      setDeleteTarget(null);
    },
  });

  // Device tokens queries and mutations
  const devicesQuery = useDeviceTokens();

  const revokeToken = useRevokeDeviceToken({
    onSuccess: () => {
      toast.success(t("security.revokeSuccess"));
    },
    onError: () => {
      toast.error(t("security.revokeError"));
    },
    onSettled: () => {
      setRevokeTarget(null);
    },
  });

  const handleCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) {
      toast.error(t("security.nameRequired"));
      return;
    }
    const payload: { name: string; expires_at?: string | null } = { name: trimmedName };
    if (expiresAtInput) {
      const parsed = new Date(expiresAtInput);
      if (!Number.isNaN(parsed.getTime())) {
        payload.expires_at = parsed.toISOString();
      }
    }
    createKey.mutate(payload);
  };

  const handleRevoke = () => {
    if (revokeTarget) {
      revokeToken.mutate(revokeTarget.id);
    }
  };

  const apiKeys = useMemo(() => apiKeysQuery.data?.keys ?? [], [apiKeysQuery.data?.keys]);
  const devices = useMemo(() => devicesQuery.data ?? [], [devicesQuery.data]);

  const copySecret = () => {
    if (!generatedSecret || !navigator?.clipboard) {
      return;
    }
    void navigator.clipboard.writeText(generatedSecret).then(() => {
      toast.success(t("security.keyCopied"));
    });
  };

  return (
    <div className="space-y-6">
      {/* Device Tokens Section */}
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("security.devicesTitle")}</CardTitle>
          <CardDescription>{t("security.devicesDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {devicesQuery.isLoading ? (
            <p className="text-muted-foreground text-sm">{t("security.loadingDevices")}</p>
          ) : devicesQuery.isError ? (
            <p className="text-destructive text-sm">{t("security.devicesError")}</p>
          ) : devices.length === 0 ? (
            <div className="text-muted-foreground flex flex-col items-center gap-3 py-6 text-center">
              <Smartphone className="h-10 w-10 opacity-50" />
              <div>
                <p className="font-medium">{t("security.noDevices")}</p>
                <p className="text-sm">{t("security.noDevicesHint")}</p>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {devices.map((device) => (
                <div
                  key={device.id}
                  className="flex items-center justify-between gap-4 rounded-lg border p-4"
                >
                  <div className="flex items-center gap-3">
                    <div className="bg-muted flex h-10 w-10 items-center justify-center rounded-full">
                      <Smartphone className="h-5 w-5" />
                    </div>
                    <div>
                      <p className="font-medium">
                        {device.device_name ?? t("security.unknownDevice")}
                      </p>
                      <p className="text-muted-foreground text-sm">
                        {t("security.loggedIn", { date: formatDateTime(device.created_at) })}
                      </p>
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setRevokeTarget(device)}
                    disabled={revokeToken.isPending}
                  >
                    <Trash2 className="mr-1.5 h-4 w-4" />
                    {t("security.revoke")}
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* API Keys Section */}
      {generatedSecret ? (
        <Card className="border-primary/50 shadow-sm">
          <CardHeader>
            <CardTitle>{t("security.newKeyTitle")}</CardTitle>
            <CardDescription>{t("security.newKeyDescription")}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap items-start gap-4">
            <code className="bg-muted flex-1 rounded-md border px-3 py-2 font-mono text-sm break-all">
              {generatedSecret}
            </code>
            <Button type="button" variant="secondary" onClick={copySecret}>
              {t("security.copy")}
            </Button>
          </CardContent>
        </Card>
      ) : null}

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("security.generateTitle")}</CardTitle>
          <CardDescription>{t("security.generateDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleCreate}>
            <div className="space-y-2">
              <Label htmlFor="api-key-name">{t("security.keyNameLabel")}</Label>
              <Input
                id="api-key-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t("security.keyNamePlaceholder")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="api-key-expiration">{t("security.expirationLabel")}</Label>
              <DateTimePicker
                id="api-key-expiration"
                value={expiresAtInput}
                onChange={setExpiresAtInput}
                placeholder={t("security.neverExpires")}
                calendarProps={{
                  hidden: {
                    before: new Date(),
                  },
                }}
              />
              <p className="text-muted-foreground text-xs">{t("security.expirationHelp")}</p>
            </div>
            <Button type="submit" disabled={createKey.isPending}>
              {createKey.isPending ? t("security.generating") : t("security.generateButton")}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("security.existingTitle")}</CardTitle>
          <CardDescription>{t("security.existingDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {apiKeysQuery.isLoading ? (
            <p className="text-muted-foreground text-sm">{t("security.loadingKeys")}</p>
          ) : apiKeysQuery.isError ? (
            <p className="text-destructive text-sm">{t("security.keysError")}</p>
          ) : apiKeys.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("security.noKeys")}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-muted-foreground text-left">
                  <tr>
                    <th className="py-2 pr-4 font-medium">{t("security.columnName")}</th>
                    <th className="py-2 pr-4 font-medium">{t("security.columnPrefix")}</th>
                    <th className="py-2 pr-4 font-medium">{t("security.columnStatus")}</th>
                    <th className="py-2 pr-4 font-medium">{t("security.columnLastUsed")}</th>
                    <th className="py-2 pr-4 font-medium">{t("security.columnExpires")}</th>
                    <th className="py-2 text-right font-medium">{t("security.columnActions")}</th>
                  </tr>
                </thead>
                <tbody>
                  {apiKeys.map((key) => {
                    const status = computeStatus(key);
                    return (
                      <tr key={key.id} className="border-t">
                        <td className="py-3 pr-4">
                          <div className="font-medium">{key.name}</div>
                          <div className="text-muted-foreground text-xs">
                            {formatDateTime(key.created_at)}
                          </div>
                        </td>
                        <td className="py-3 pr-4 font-mono">{key.token_prefix}...</td>
                        <td className="py-3 pr-4">
                          <Badge variant={status.variant}>{t(status.labelKey)}</Badge>
                        </td>
                        <td className="py-3 pr-4">
                          {key.last_used_at
                            ? formatDateTime(key.last_used_at)
                            : t("security.never")}
                        </td>
                        <td className="py-3 pr-4">{formatDateTime(key.expires_at)}</td>
                        <td className="py-3 text-right">
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => deleteKey.mutate(key.id)}
                            disabled={deleteTarget === key.id && deleteKey.isPending}
                          >
                            {deleteTarget === key.id && deleteKey.isPending
                              ? t("security.deleting")
                              : t("security.deleteButton")}
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Revoke Device Dialog */}
      <AlertDialog open={revokeTarget !== null} onOpenChange={() => setRevokeTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("security.revokeDialogTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              <Trans
                i18nKey="security.revokeDialogDescription"
                ns="settings"
                values={{ deviceName: revokeTarget?.device_name ?? t("security.unknownDevice") }}
                components={{ bold: <span className="font-medium" /> }}
              />
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("security.revokeDialogCancel")}</AlertDialogCancel>
            <AlertDialogAction onClick={handleRevoke} disabled={revokeToken.isPending}>
              {revokeToken.isPending ? t("security.revoking") : t("security.revokeDialogConfirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};
