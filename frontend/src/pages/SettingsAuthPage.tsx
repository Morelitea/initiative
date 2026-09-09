import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { AuthProvidersSection } from "@/components/admin/AuthProvidersSection";
import { OidcClaimMappingsSection } from "@/components/admin/OidcClaimMappingsSection";
import { FormSkeleton, SkeletonRegion } from "@/components/skeletons/PageSkeletons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/hooks/useAuth";
import { useServerForm } from "@/hooks/useServerForm";
import { useOidcSettings, useUpdateOidcSettings } from "@/hooks/useSettings";
import { Capability, hasCapability } from "@/lib/permissions";

interface OidcSettings {
  enabled: boolean;
  issuer?: string | null;
  client_id?: string | null;
  redirect_uri?: string | null;
  post_login_redirect?: string | null;
  mobile_redirect_uri?: string | null;
  provider_name?: string | null;
  scopes: string[];
}

export const SettingsAuthPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const isPlatformAdmin = hasCapability(user, Capability.configManage);
  const [clientSecret, setClientSecret] = useState("");
  const oidcQuery = useOidcSettings({ enabled: isPlatformAdmin });

  // A provider is described across five fields and saved once at the end, so a
  // refetch part-way through must not take the description back.
  const form = useServerForm(
    oidcQuery.data,
    (settings) => ({
      enabled: settings?.enabled ?? false,
      issuer: settings?.issuer ?? "",
      client_id: settings?.client_id ?? "",
      provider_name: settings?.provider_name ?? "",
      scopes: settings?.scopes.join(" ") ?? "openid profile email offline_access",
    }),
    "oidc"
  );

  const updateOidcSettings = useUpdateOidcSettings({
    onSuccess: () => {
      setClientSecret("");
      form.settle();
    },
  });

  if (oidcQuery.isLoading) {
    if (!isPlatformAdmin) {
      return <p className="text-muted-foreground text-sm">{t("auth.adminOnly")}</p>;
    }
    return (
      <SkeletonRegion label={t("auth.loading")}>
        <FormSkeleton fields={5} />
      </SkeletonRegion>
    );
  }

  if (!isPlatformAdmin) {
    return <p className="text-muted-foreground text-sm">{t("auth.adminOnly")}</p>;
  }

  if (oidcQuery.isError || !oidcQuery.data) {
    return <p className="text-destructive text-sm">{t("auth.loadError")}</p>;
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    updateOidcSettings.mutate({
      enabled: form.values.enabled,
      issuer: form.values.issuer || null,
      client_id: form.values.client_id || null,
      provider_name: form.values.provider_name || null,
      scopes: form.values.scopes.split(/[\s,]+/).filter(Boolean),
      client_secret: clientSecret || undefined,
    } as OidcSettings & { client_secret?: string });
  };

  const authScope = oidcQuery.data.auth_scope;

  return (
    <div className="space-y-6">
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {t("auth.title")}
            {/* Login posture is a deploy-time setting (AUTH_SCOPE); a badge is
                all that's needed to show which one the instance runs. */}
            <Badge variant="secondary">
              {authScope === "guild" ? t("auth.scope.guildLabel") : t("auth.scope.platformLabel")}
            </Badge>
          </CardTitle>
          <CardDescription>{t("auth.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="flex items-center justify-between rounded-md border bg-muted/40 px-3 py-2">
              <div>
                <Label
                  htmlFor="oidc-enabled"
                  className="flex items-center gap-2 font-medium text-base"
                >
                  {t("auth.enabledLabel")}
                </Label>
                <p className="text-muted-foreground text-sm">{t("auth.enabledHelp")}</p>
              </div>
              <Switch
                id="oidc-enabled"
                checked={form.values.enabled}
                onCheckedChange={(checked) => form.set({ enabled: Boolean(checked) })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="issuer">{t("auth.issuerLabel")}</Label>
              <Input
                id="issuer"
                type="url"
                value={form.values.issuer}
                onChange={(event) => form.set({ issuer: event.target.value })}
                placeholder={t("auth.issuerPlaceholder")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="client-id">{t("auth.clientIdLabel")}</Label>
              <Input
                id="client-id"
                value={form.values.client_id}
                onChange={(event) => form.set({ client_id: event.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="client-secret">{t("auth.clientSecretLabel")}</Label>
              <Input
                id="client-secret"
                type="password"
                value={clientSecret}
                onChange={(event) => setClientSecret(event.target.value)}
                placeholder={t("auth.clientSecretPlaceholder")}
              />
              <p className="text-muted-foreground text-xs">{t("auth.clientSecretHelp")}</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="provider-name">{t("auth.providerNameLabel")}</Label>
              <Input
                id="provider-name"
                value={form.values.provider_name}
                onChange={(event) => form.set({ provider_name: event.target.value })}
                placeholder={t("auth.providerNamePlaceholder")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="scopes">{t("auth.scopesLabel")}</Label>
              <Input
                id="scopes"
                value={form.values.scopes}
                onChange={(event) => form.set({ scopes: event.target.value })}
                placeholder={t("auth.scopesPlaceholder")}
              />
            </div>
            <Button type="submit" disabled={updateOidcSettings.isPending}>
              {updateOidcSettings.isPending ? t("auth.saving") : t("auth.save")}
            </Button>
          </form>
        </CardContent>
        <CardFooter className="flex flex-col gap-2 text-muted-foreground text-sm">
          <div>
            {t("auth.callbackUrl")}{" "}
            <code className="rounded bg-muted px-1 py-0.5">{oidcQuery.data.redirect_uri}</code>
          </div>
          <div>
            {t("auth.postLoginRedirect")}{" "}
            <code className="rounded bg-muted px-1 py-0.5">
              {oidcQuery.data.post_login_redirect}
            </code>
          </div>
          <div>
            {t("auth.mobileCallback")}{" "}
            <code className="rounded bg-muted px-1 py-0.5">
              {oidcQuery.data.mobile_redirect_uri}
            </code>
          </div>
        </CardFooter>
      </Card>
      <AuthProvidersSection />
      <OidcClaimMappingsSection />
    </div>
  );
};
