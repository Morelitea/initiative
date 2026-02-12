import { FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { apiClient } from "@/api/client";
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
import { OidcClaimMappingsSection } from "@/components/admin/OidcClaimMappingsSection";

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
  const { user } = useAuth();
  const isPlatformAdmin = user?.role === "admin";
  const [clientSecret, setClientSecret] = useState("");
  const [formState, setFormState] = useState({
    enabled: false,
    issuer: "",
    client_id: "",
    provider_name: "",
    scopes: "openid profile email offline_access",
  });

  const oidcQuery = useQuery<OidcSettings>({
    queryKey: ["settings", "oidc"],
    enabled: isPlatformAdmin,
    queryFn: async () => {
      const response = await apiClient.get<OidcSettings>("/settings/auth");
      return response.data;
    },
  });

  const updateOidcSettings = useMutation({
    mutationFn: async (payload: OidcSettings & { client_secret?: string }) => {
      const response = await apiClient.put<OidcSettings>("/settings/auth", payload);
      return response.data;
    },
    onSuccess: () => {
      void oidcQuery.refetch();
      setClientSecret("");
    },
  });

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
      return (
        <p className="text-muted-foreground text-sm">
          Only platform admins can manage authentication settings.
        </p>
      );
    }
    return <p className="text-muted-foreground text-sm">Loading auth settings…</p>;
  }

  if (!isPlatformAdmin) {
    return (
      <p className="text-muted-foreground text-sm">
        Only platform admins can manage authentication settings.
      </p>
    );
  }

  if (oidcQuery.isError || !oidcQuery.data) {
    return <p className="text-destructive text-sm">Unable to load auth settings.</p>;
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
    });
  };

  return (
    <div className="space-y-6">
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>OIDC authentication</CardTitle>
          <CardDescription>Configure single sign-on for your workspace.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="bg-muted/40 flex items-center justify-between rounded-md border px-3 py-2">
              <div>
                <Label
                  htmlFor="oidc-enabled"
                  className="flex items-center gap-2 text-base font-medium"
                >
                  Enabled
                </Label>
                <p className="text-muted-foreground text-sm">
                  Allow users to authenticate via your OIDC provider.
                </p>
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
              <Label htmlFor="issuer">Issuer</Label>
              <Input
                id="issuer"
                type="url"
                value={formState.issuer}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, issuer: event.target.value }))
                }
                placeholder="https://accounts.example.com"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="client-id">Client ID</Label>
              <Input
                id="client-id"
                value={formState.client_id}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, client_id: event.target.value }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="client-secret">Client secret</Label>
              <Input
                id="client-secret"
                type="password"
                value={clientSecret}
                onChange={(event) => setClientSecret(event.target.value)}
                placeholder="••••••••"
              />
              <p className="text-muted-foreground text-xs">
                Leave blank to keep the existing secret.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="provider-name">Provider name</Label>
              <Input
                id="provider-name"
                value={formState.provider_name}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, provider_name: event.target.value }))
                }
                placeholder="Single Sign-On"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="scopes">Scopes</Label>
              <Input
                id="scopes"
                value={formState.scopes}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, scopes: event.target.value }))
                }
                placeholder="openid profile email offline_access"
              />
            </div>
            <Button type="submit" disabled={updateOidcSettings.isPending}>
              {updateOidcSettings.isPending ? "Saving…" : "Save auth settings"}
            </Button>
          </form>
        </CardContent>
        <CardFooter className="text-muted-foreground flex flex-col gap-2 text-sm">
          <div>
            Authorization callback:{" "}
            <code className="bg-muted rounded px-1 py-0.5">{oidcQuery.data.redirect_uri}</code>
          </div>
          <div>
            Post-login redirect:{" "}
            <code className="bg-muted rounded px-1 py-0.5">
              {oidcQuery.data.post_login_redirect}
            </code>
          </div>
          <div>
            Mobile app callback:{" "}
            <code className="bg-muted rounded px-1 py-0.5">
              {oidcQuery.data.mobile_redirect_uri}
            </code>
          </div>
        </CardFooter>
      </Card>
      <OidcClaimMappingsSection />
    </div>
  );
};
