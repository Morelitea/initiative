import { KeyRound, Plus } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ApiKeyMetadata } from "@/api/generated/initiativeAPI.schemas";
import { PasskeysSection } from "@/components/settings/PasskeysSection";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { SignedInSection } from "@/components/settings/SignedInSection";
import { TwoFactorSection } from "@/components/settings/TwoFactorSection";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DateTimePicker } from "@/components/ui/date-time-picker";
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
import { useGuilds } from "@/hooks/useGuilds";
import { useCreateApiKey, useDeleteApiKey, useMyApiKeys } from "@/hooks/useSecurity";
import { toast } from "@/lib/chesterToast";
import { formatDateTime } from "@/lib/formatDate";

const computeStatus = (key: ApiKeyMetadata) => {
  if (!key.is_active) {
    return { labelKey: "security.statusDisabled" as const, variant: "destructive" as const };
  }
  if (key.expires_at && new Date(key.expires_at).getTime() <= Date.now()) {
    return { labelKey: "security.statusExpired" as const, variant: "secondary" as const };
  }
  return null;
};

/**
 * Making an API key: the form, then the secret, which is shown once.
 */
const NewApiKeyDialog = ({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) => {
  const { t } = useTranslation(["settings", "common"]);
  const { guilds } = useGuilds();
  const [name, setName] = useState("");
  const [expiresAtInput, setExpiresAtInput] = useState("");
  const [readOnly, setReadOnly] = useState(false);
  const [guildId, setGuildId] = useState<string>("all");
  const [secret, setSecret] = useState<string | null>(null);

  const close = () => {
    onOpenChange(false);
    setName("");
    setExpiresAtInput("");
    setReadOnly(false);
    setGuildId("all");
    setSecret(null);
  };

  const createKey = useCreateApiKey({
    onSuccess: (data) => setSecret(data.secret),
    onError: () => toast.error(t("security.createError")),
  });

  const handleCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) {
      toast.error(t("security.nameRequired"));
      return;
    }
    const payload: {
      name: string;
      expires_at?: string | null;
      read_only?: boolean;
      community_id?: number | null;
    } = { name: trimmedName, read_only: readOnly };
    if (expiresAtInput) {
      const parsed = new Date(expiresAtInput);
      if (!Number.isNaN(parsed.getTime())) {
        payload.expires_at = parsed.toISOString();
      }
    }
    if (guildId !== "all") {
      payload.community_id = Number(guildId);
    }
    createKey.mutate(payload);
  };

  const copySecret = () => {
    if (!secret || !navigator?.clipboard) {
      return;
    }
    void navigator.clipboard.writeText(secret).then(() => {
      toast.success(t("security.keyCopied"));
    });
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent>
        {secret ? (
          <>
            <DialogHeader>
              <DialogTitle>{t("security.newKeyTitle")}</DialogTitle>
              <DialogDescription>{t("security.newKeyDescription")}</DialogDescription>
            </DialogHeader>
            <code className="block break-all rounded-md border bg-muted px-3 py-2 font-mono text-sm">
              {secret}
            </code>
            <DialogFooter className="gap-2">
              <Button type="button" variant="outline" onClick={copySecret}>
                {t("security.copy")}
              </Button>
              <Button type="button" onClick={close}>
                {t("common:done")}
              </Button>
            </DialogFooter>
          </>
        ) : (
          <form onSubmit={handleCreate} className="space-y-4">
            <DialogHeader>
              <DialogTitle>{t("security.generateTitle")}</DialogTitle>
            </DialogHeader>
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
              <Label htmlFor="api-key-guild">{t("security.guildLabel")}</Label>
              <Select value={guildId} onValueChange={setGuildId}>
                <SelectTrigger id="api-key-guild">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("security.guildAllGuilds")}</SelectItem>
                  {guilds.map((guild) => (
                    <SelectItem key={guild.id} value={String(guild.id)}>
                      {guild.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-muted-foreground text-xs">{t("security.guildHelp")}</p>
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
            </div>
            <div className="flex items-start gap-2">
              <Checkbox
                id="api-key-read-only"
                checked={readOnly}
                onCheckedChange={(checked) => setReadOnly(checked === true)}
                className="mt-0.5"
              />
              <div className="space-y-1">
                <Label htmlFor="api-key-read-only">{t("security.readOnlyLabel")}</Label>
                <p className="text-muted-foreground text-xs">{t("security.readOnlyHelp")}</p>
              </div>
            </div>
            <DialogFooter className="gap-2">
              <Button type="button" variant="outline" onClick={close}>
                {t("common:cancel")}
              </Button>
              <Button type="submit" disabled={createKey.isPending}>
                {createKey.isPending ? t("security.generating") : t("security.generateButton")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
};

export const UserSettingsSecurityPage = () => {
  const { t } = useTranslation(["settings", "common"]);
  const [creating, setCreating] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ApiKeyMetadata | null>(null);

  const { guilds } = useGuilds();
  const guildName = (id: number) => guilds.find((guild) => guild.id === id)?.name ?? String(id);

  const apiKeysQuery = useMyApiKeys();
  const apiKeys = apiKeysQuery.data?.keys ?? [];

  const deleteKey = useDeleteApiKey({
    onSuccess: () => toast.success(t("security.deleteSuccess")),
    onError: () => toast.error(t("security.deleteError")),
    onSettled: () => setDeleteTarget(null),
  });

  return (
    <div className="space-y-6">
      <SettingsSection title={t("passkeys.title")} description={t("passkeys.description")}>
        <PasskeysSection />
      </SettingsSection>

      <SettingsSection title={t("twoFactor.title")} description={t("twoFactor.description")}>
        <TwoFactorSection />
      </SettingsSection>

      <SignedInSection />

      <SettingsSection
        title={t("security.apiKeysTitle")}
        description={t("security.apiKeysDescription")}
        action={
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" />
            {t("security.newKeyButton")}
          </Button>
        }
      >
        {apiKeysQuery.isLoading ? (
          <p className="text-muted-foreground text-sm">{t("security.loadingKeys")}</p>
        ) : apiKeysQuery.isError ? (
          <p className="text-destructive text-sm">{t("security.keysError")}</p>
        ) : apiKeys.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("security.noKeys")}</p>
        ) : (
          <ul className="space-y-3">
            {apiKeys.map((key) => {
              const status = computeStatus(key);
              const detail = [
                `${key.token_prefix}…`,
                t("security.keyCreated", { date: formatDateTime(key.created_at) }),
                key.last_used_at
                  ? t("security.keyLastUsed", { date: formatDateTime(key.last_used_at) })
                  : t("security.keyNeverUsed"),
                key.expires_at
                  ? t("security.keyExpires", { date: formatDateTime(key.expires_at) })
                  : null,
              ]
                .filter(Boolean)
                .join(" · ");
              return (
                <li
                  key={key.id}
                  className="flex items-center justify-between gap-4 rounded-lg border p-4"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-muted">
                      <KeyRound className="h-5 w-5" />
                    </div>
                    <div className="min-w-0">
                      <p className="flex flex-wrap items-center gap-2 font-medium">
                        {key.name}
                        {status ? (
                          <Badge variant={status.variant}>{t(status.labelKey)}</Badge>
                        ) : null}
                        {key.read_only ? (
                          <Badge variant="secondary">{t("security.scopeReadOnly")}</Badge>
                        ) : null}
                        {key.community_id != null ? (
                          <Badge variant="outline">
                            {t("security.scopeGuild", { guild: guildName(key.community_id) })}
                          </Badge>
                        ) : null}
                        {!key.read_only && key.community_id == null ? (
                          <Badge variant="outline">{t("security.scopeFull")}</Badge>
                        ) : null}
                      </p>
                      <p className="text-muted-foreground text-sm">{detail}</p>
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setDeleteTarget(key)}
                  >
                    {t("security.deleteButton")}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </SettingsSection>

      <NewApiKeyDialog open={creating} onOpenChange={setCreating} />

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        title={t("security.deleteDialogTitle")}
        description={t("security.deleteDialogDescription", { name: deleteTarget?.name ?? "" })}
        confirmLabel={t("security.deleteButton")}
        cancelLabel={t("common:cancel")}
        loadingLabel={t("security.deleting")}
        isLoading={deleteKey.isPending}
        destructive
        onConfirm={() => {
          if (deleteTarget) deleteKey.mutate(deleteTarget.id);
        }}
      />
    </div>
  );
};
