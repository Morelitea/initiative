import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type { AuthProviderAdminRead } from "@/api/generated/initiativeAPI.schemas";
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
  useAuthProviders,
  useCreateAuthProvider,
  useDeleteAuthProvider,
  useUpdateAuthProvider,
} from "@/hooks/useSettings";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

// Create-dialog presets: pre-fill the well-known IdPs' discovery config so an
// operator only supplies client credentials. "custom" is a blank OIDC form
// (Keycloak, Authentik, Zitadel, … all take a custom issuer).
const PRESETS = {
  custom: { slug: "", display_name: "", issuer: "", icon: null as string | null },
  google: {
    slug: "google",
    display_name: "Google",
    issuer: "https://accounts.google.com",
    icon: "google",
  },
  microsoft: {
    slug: "microsoft",
    display_name: "Microsoft",
    issuer: "https://login.microsoftonline.com/{tenant}/v2.0",
    icon: "microsoft",
  },
} as const;
type PresetKey = keyof typeof PRESETS;

interface ProviderFormState {
  slug: string;
  display_name: string;
  issuer: string;
  client_id: string;
  client_secret: string;
  scopes: string;
  allow_jit: boolean;
  enabled: boolean;
}

const EMPTY_FORM: ProviderFormState = {
  slug: "",
  display_name: "",
  issuer: "",
  client_id: "",
  client_secret: "",
  scopes: "openid email profile",
  allow_jit: true,
  enabled: true,
};

// Mirrors the backend's validate_provider_slug: lowercase ASCII letters,
// digits, and inner dashes; no leading/trailing dash.
const SLUG_CHARS = new Set("abcdefghijklmnopqrstuvwxyz0123456789-");
const isValidSlug = (value: string) =>
  value.length >= 1 &&
  value.length <= 64 &&
  [...value].every((ch) => SLUG_CHARS.has(ch)) &&
  !value.startsWith("-") &&
  !value.endsWith("-");

export const AuthProvidersSection = () => {
  const { t } = useTranslation("settings");
  const providersQuery = useAuthProviders();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<AuthProviderAdminRead | null>(null);
  const [preset, setPreset] = useState<PresetKey>("custom");
  const [form, setForm] = useState<ProviderFormState>(EMPTY_FORM);
  const [clearSecret, setClearSecret] = useState(false);
  const [slugError, setSlugError] = useState(false);
  const [deleting, setDeleting] = useState<AuthProviderAdminRead | null>(null);

  const closeDialog = () => {
    setDialogOpen(false);
    setEditing(null);
    setPreset("custom");
    setForm(EMPTY_FORM);
    setClearSecret(false);
    setSlugError(false);
  };

  const createProvider = useCreateAuthProvider({
    onSuccess: () => {
      toast.success(t("authProviders.created"));
      closeDialog();
    },
    onError: (error) => toast.error(getErrorMessage(error, "settings:authProviders.saveError")),
  });
  const updateProvider = useUpdateAuthProvider({
    onSuccess: () => {
      toast.success(t("authProviders.saved"));
      closeDialog();
    },
    onError: (error) => toast.error(getErrorMessage(error, "settings:authProviders.saveError")),
  });
  const deleteProvider = useDeleteAuthProvider({
    onSuccess: () => {
      toast.success(t("authProviders.deleted"));
      setDeleting(null);
    },
    onError: (error) => toast.error(getErrorMessage(error, "settings:authProviders.deleteError")),
  });

  const openCreate = () => {
    setEditing(null);
    setPreset("custom");
    setForm(EMPTY_FORM);
    setClearSecret(false);
    setSlugError(false);
    setDialogOpen(true);
  };

  const openEdit = (provider: AuthProviderAdminRead) => {
    setEditing(provider);
    setForm({
      slug: provider.slug,
      display_name: provider.display_name,
      issuer: provider.issuer ?? "",
      client_id: provider.client_id ?? "",
      client_secret: "",
      scopes: provider.scopes ?? "",
      allow_jit: provider.allow_jit,
      enabled: provider.enabled,
    });
    setClearSecret(false);
    setSlugError(false);
    setDialogOpen(true);
  };

  const applyPreset = (key: PresetKey) => {
    setPreset(key);
    setSlugError(false);
    const values = PRESETS[key];
    setForm((prev) => ({
      ...prev,
      slug: values.slug,
      display_name: values.display_name,
      issuer: values.issuer,
    }));
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editing && !isValidSlug(form.slug)) {
      setSlugError(true);
      return;
    }
    if (editing) {
      updateProvider.mutate({
        providerId: editing.id,
        data: {
          display_name: form.display_name,
          issuer: form.issuer,
          client_id: form.client_id,
          scopes: form.scopes || null,
          allow_jit: form.allow_jit,
          enabled: form.enabled,
          // Write-only secret: absent keeps, empty string clears.
          ...(clearSecret
            ? { client_secret: "" }
            : form.client_secret
              ? { client_secret: form.client_secret }
              : {}),
        },
      });
    } else {
      createProvider.mutate({
        slug: form.slug,
        display_name: form.display_name,
        issuer: form.issuer,
        client_id: form.client_id,
        client_secret: form.client_secret || null,
        scopes: form.scopes || null,
        allow_jit: form.allow_jit,
        enabled: form.enabled,
        icon: PRESETS[preset].icon,
      });
    }
  };

  const providers = providersQuery.data ?? [];
  const saving = createProvider.isPending || updateProvider.isPending;

  return (
    <Card className="shadow-sm">
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle>{t("authProviders.title")}</CardTitle>
          <CardDescription>{t("authProviders.description")}</CardDescription>
        </div>
        <Button type="button" onClick={openCreate}>
          {t("authProviders.addProvider")}
        </Button>
      </CardHeader>
      <CardContent>
        {providersQuery.isLoading ? (
          <p className="text-muted-foreground text-sm">{t("authProviders.loading")}</p>
        ) : providers.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("authProviders.empty")}</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {providers.map((provider) => (
              <li key={provider.id} className="flex items-center justify-between gap-4 px-3 py-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{provider.display_name}</span>
                    <code className="rounded bg-muted px-1 py-0.5 text-xs">{provider.slug}</code>
                    {!provider.enabled && (
                      <Badge variant="outline">{t("authProviders.disabledBadge")}</Badge>
                    )}
                    {provider.reserved && (
                      <Badge variant="secondary">{t("authProviders.reservedBadge")}</Badge>
                    )}
                  </div>
                  <p className="truncate text-muted-foreground text-sm">{provider.issuer}</p>
                </div>
                {provider.reserved ? (
                  <p className="shrink-0 text-muted-foreground text-xs">
                    {t("authProviders.reservedHelp")}
                  </p>
                ) : (
                  <div className="flex shrink-0 gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => openEdit(provider)}
                    >
                      {t("authProviders.edit")}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="text-destructive"
                      onClick={() => setDeleting(provider)}
                    >
                      {t("authProviders.delete")}
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>

      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => (open ? setDialogOpen(true) : closeDialog())}
      >
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {editing ? t("authProviders.editTitle") : t("authProviders.createTitle")}
            </DialogTitle>
            <DialogDescription>{t("authProviders.dialogDescription")}</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={handleSubmit}>
            {!editing && (
              <div className="space-y-2">
                <Label htmlFor="provider-preset">{t("authProviders.presetLabel")}</Label>
                <Select value={preset} onValueChange={(value) => applyPreset(value as PresetKey)}>
                  <SelectTrigger id="provider-preset">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="custom">{t("authProviders.presetCustom")}</SelectItem>
                    <SelectItem value="google">Google</SelectItem>
                    <SelectItem value="microsoft">Microsoft Entra ID</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="provider-slug">{t("authProviders.slugLabel")}</Label>
              <Input
                id="provider-slug"
                value={form.slug}
                onChange={(event) => {
                  setSlugError(false);
                  setForm((prev) => ({ ...prev, slug: event.target.value }));
                }}
                maxLength={64}
                disabled={Boolean(editing)}
                required
              />
              {slugError ? (
                <p className="text-destructive text-xs">{t("authProviders.slugInvalid")}</p>
              ) : (
                <p className="text-muted-foreground text-xs">{t("authProviders.slugHelp")}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="provider-display-name">{t("authProviders.displayNameLabel")}</Label>
              <Input
                id="provider-display-name"
                value={form.display_name}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, display_name: event.target.value }))
                }
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="provider-issuer">{t("authProviders.issuerLabel")}</Label>
              <Input
                id="provider-issuer"
                type="url"
                value={form.issuer}
                onChange={(event) => setForm((prev) => ({ ...prev, issuer: event.target.value }))}
                placeholder={t("authProviders.issuerPlaceholder")}
                required
              />
              {preset === "microsoft" && !editing && (
                <p className="text-muted-foreground text-xs">{t("authProviders.tenantHelp")}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="provider-client-id">{t("authProviders.clientIdLabel")}</Label>
              <Input
                id="provider-client-id"
                value={form.client_id}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, client_id: event.target.value }))
                }
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="provider-client-secret">{t("authProviders.clientSecretLabel")}</Label>
              <Input
                id="provider-client-secret"
                type="password"
                value={form.client_secret}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, client_secret: event.target.value }))
                }
                placeholder={
                  editing?.secret_set
                    ? t("authProviders.secretKeepPlaceholder")
                    : t("authProviders.secretPlaceholder")
                }
                disabled={clearSecret}
              />
              {editing?.secret_set && (
                <label className="flex items-center gap-2 text-muted-foreground text-xs">
                  <input
                    type="checkbox"
                    checked={clearSecret}
                    onChange={(event) => setClearSecret(event.target.checked)}
                  />
                  {t("authProviders.clearSecret")}
                </label>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="provider-scopes">{t("authProviders.scopesLabel")}</Label>
              <Input
                id="provider-scopes"
                value={form.scopes}
                onChange={(event) => setForm((prev) => ({ ...prev, scopes: event.target.value }))}
              />
            </div>
            <div className="flex items-center justify-between rounded-md border bg-muted/40 px-3 py-2">
              <div>
                <Label htmlFor="provider-allow-jit" className="font-medium">
                  {t("authProviders.allowJitLabel")}
                </Label>
                <p className="text-muted-foreground text-xs">{t("authProviders.allowJitHelp")}</p>
              </div>
              <Switch
                id="provider-allow-jit"
                checked={form.allow_jit}
                onCheckedChange={(checked) =>
                  setForm((prev) => ({ ...prev, allow_jit: Boolean(checked) }))
                }
              />
            </div>
            <div className="flex items-center justify-between rounded-md border bg-muted/40 px-3 py-2">
              <Label htmlFor="provider-enabled" className="font-medium">
                {t("authProviders.enabledLabel")}
              </Label>
              <Switch
                id="provider-enabled"
                checked={form.enabled}
                onCheckedChange={(checked) =>
                  setForm((prev) => ({ ...prev, enabled: Boolean(checked) }))
                }
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={closeDialog} disabled={saving}>
                {t("authProviders.cancel")}
              </Button>
              <Button type="submit" disabled={saving}>
                {saving ? t("authProviders.saving") : t("authProviders.save")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={t("authProviders.deleteTitle", { name: deleting?.display_name ?? "" })}
        description={t("authProviders.deleteDescription")}
        confirmLabel={t("authProviders.delete")}
        cancelLabel={t("authProviders.cancel")}
        destructive
        isLoading={deleteProvider.isPending}
        onConfirm={() => {
          if (deleting) {
            deleteProvider.mutate(deleting.id);
          }
        }}
      />
    </Card>
  );
};
