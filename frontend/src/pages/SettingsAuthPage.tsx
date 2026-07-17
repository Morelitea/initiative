import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { AuthProvidersSection } from "@/components/admin/AuthProvidersSection";
import { OidcClaimMappingsSection } from "@/components/admin/OidcClaimMappingsSection";
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
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/hooks/useAuth";
import { useOidcSettings, useUpdateAuthScope, useUpdateOidcSettings } from "@/hooks/useSettings";
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
  const [formState, setFormState] = useState({
    enabled: false,
    issuer: "",
    client_id: "",
    provider_name: "",
    scopes: "openid profile email offline_access",
  });

  const oidcQuery = useOidcSettings({ enabled: isPlatformAdmin });

  const updateOidcSettings = useUpdateOidcSettings({
    onSuccess: () => {
      setClientSecret("");
    },
  });
  const updateAuthScope = useUpdateAuthScope();

  useEffect(() => {
    if (oidcQuery.data) {
      const settings = oidcQuery.data;
      setFormState({
        enabled: settings.enabled,
        issuer: settings.issuer ?? "",
        client_id: settings.client_id ?? "",
        provider_name: settings.provider_name ?? "",
        scopes: settings.scopes.join(" "),
      });
    }
  }, [oidcQuery.data]);

  if (oidcQuery.isLoading) {
    if (!isPlatformAdmin) {
      return <p className="text-muted-foreground text-sm">{t("auth.adminOnly")}</p>;
    }
    return <p className="text-muted-foreground text-sm">{t("auth.loading")}</p>;
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
      enabled: formState.enabled,
      issuer: formState.issuer || null,
      client_id: formState.client_id || null,
      provider_name: formState.provider_name || null,
      scopes: formState.scopes.split(/[\s,]+/).filter(Boolean),
      client_secret: clientSecret || undefined,
    } as OidcSettings & { client_secret?: string });
  };

  const authScope = oidcQuery.data.auth_scope;

  return (
    <div className="space-y-6">
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("auth.scope.title")}</CardTitle>
          <CardDescription>{t("auth.scope.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <RadioGroup
            value={authScope}
            onValueChange={(value) => {
              if (value !== authScope) {
                updateAuthScope.mutate({ scope: value as "platform" | "guild" });
              }
            }}
            className="gap-3"
          >
            <div className="flex items-start gap-3 rounded-md border px-3 py-3">
              <RadioGroupItem id="auth-scope-platform" value="platform" className="mt-1" />
              <div>
                <Label htmlFor="auth-scope-platform" className="font-medium text-base">
                  {t("auth.scope.platformLabel")}
                </Label>
                <p className="text-muted-foreground text-sm">{t("auth.scope.platformHelp")}</p>
              </div>
            </div>
            {/* Per-guild sign-in ships disabled until guild-side configuration
                exists; the backend + enforcement are already wired. */}
            <div className="flex items-start gap-3 rounded-md border px-3 py-3 opacity-70">
              <RadioGroupItem id="auth-scope-guild" value="guild" disabled className="mt-1" />
              <div>
                <Label
                  htmlFor="auth-scope-guild"
                  className="flex items-center gap-2 font-medium text-base"
                >
                  {t("auth.scope.guildLabel")}
                  <Badge variant="secondary">{t("auth.scope.comingSoon")}</Badge>
                </Label>
                <p className="text-muted-foreground text-sm">{t("auth.scope.guildHelp")}</p>
              </div>
            </div>
          </RadioGroup>
          <p className="text-muted-foreground text-sm">{t("auth.scope.passwordNote")}</p>
        </CardContent>
      </Card>
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("auth.title")}</CardTitle>
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
                checked={formState.enabled}
                onCheckedChange={(checked) =>
                  setFormState((prev) => ({ ...prev, enabled: Boolean(checked) }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="issuer">{t("auth.issuerLabel")}</Label>
              <Input
                id="issuer"
                type="url"
                value={formState.issuer}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, issuer: event.target.value }))
                }
                placeholder={t("auth.issuerPlaceholder")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="client-id">{t("auth.clientIdLabel")}</Label>
              <Input
                id="client-id"
                value={formState.client_id}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, client_id: event.target.value }))
                }
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
                value={formState.provider_name}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, provider_name: event.target.value }))
                }
                placeholder={t("auth.providerNamePlaceholder")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="scopes">{t("auth.scopesLabel")}</Label>
              <Input
                id="scopes"
                value={formState.scopes}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, scopes: event.target.value }))
                }
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
