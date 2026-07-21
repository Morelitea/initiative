import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { GuildAuthProvidersSection } from "@/components/auth/GuildAuthProvidersSection";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import {
  useGuildAuthPolicy,
  useGuildAuthProviders,
  useGuildLoginProviders,
  useUpdateGuildAuthPolicy,
} from "@/hooks/useGuildAuthPolicy";
import { useGuilds } from "@/hooks/useGuilds";
import { useServer } from "@/hooks/useServer";
import { useInterfaceSettings } from "@/hooks/useSettings";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

/**
 * Guild sign-in configuration (Settings → Authentication): the guild's own
 * identity provider registry, and the sign-in requirement a guild admin can
 * set against it — sessions reach this guild only after signing in through
 * one specific provider; `open` (the default) admits any signed-in session.
 */
export const SettingsGuildAuthPage = () => {
  const { t } = useTranslation(["settings", "common"]);
  const guildId = useActiveGuildId();

  // The whole page exists only when the platform has opted into per-guild auth
  // AND an operator has enabled sign-in for this guild; outside that the tab is
  // hidden and a direct URL renders nothing (fail closed while still loading).
  // The backend 404s the policy/provider endpoints in the same case, so the
  // queries stay off too.
  const interfaceSettings = useInterfaceSettings();
  const { activeGuild } = useGuilds();
  const guildPostureActive =
    interfaceSettings.data?.auth_scope === "guild" && activeGuild?.guild_auth_enabled === true;

  const policyQuery = useGuildAuthPolicy(guildId, {
    enabled: guildId > 0 && guildPostureActive,
  });
  const providersQuery = useGuildAuthProviders(guildId, {
    enabled: guildId > 0 && guildPostureActive,
  });
  // Only the guild's enabled providers can be required — a disabled row can't
  // serve a sign-in, so requiring it would lock the guild.
  const eligibleProviders = useMemo(
    () => (providersQuery.data ?? []).filter((entry) => entry.enabled),
    [providersQuery.data]
  );

  const [policy, setPolicy] = useState<"open" | "required">("open");
  const [providerId, setProviderId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selfUnsatisfiedSlug, setSelfUnsatisfiedSlug] = useState<string | null>(null);

  useEffect(() => {
    if (policyQuery.data) {
      setPolicy(policyQuery.data.policy);
      setProviderId(policyQuery.data.provider_id ?? null);
    }
  }, [policyQuery.data]);

  const updatePolicy = useUpdateGuildAuthPolicy(guildId);

  const selectedProvider = eligibleProviders.find((entry) => entry.id === providerId);
  const isDirty =
    policyQuery.data != null &&
    (policy !== policyQuery.data.policy ||
      (policy === "required" && providerId !== (policyQuery.data.provider_id ?? null)));
  const canSave = policy === "open" || providerId != null;

  const save = () => {
    updatePolicy.mutate(
      policy === "open"
        ? { policy: "open" }
        : { policy: "required", provider_id: providerId as number },
      {
        onSuccess: () => {
          setError(null);
          setSelfUnsatisfiedSlug(null);
          toast.success(t("guildAuth.policy.saved"));
        },
        onError: (err: unknown) => {
          const detail = (err as { response?: { data?: { detail?: string } } }).response?.data
            ?.detail;
          if (detail === "GUILD_AUTH_POLICY_SELF_UNSATISFIED") {
            const chosen = eligibleProviders.find((entry) => entry.id === providerId);
            setSelfUnsatisfiedSlug(chosen?.slug ?? null);
            setError(null);
            return;
          }
          setSelfUnsatisfiedSlug(null);
          setError(getErrorMessage(err, "settings:guildAuth.policy.error"));
        },
      }
    );
  };

  // The self-unsatisfied challenge is bound to the selection that produced
  // it: any change of policy or provider invalidates it (otherwise the
  // alert's button could name one provider while targeting another).
  const changePolicy = (value: "open" | "required") => {
    setPolicy(value);
    setSelfUnsatisfiedSlug(null);
    setError(null);
  };
  const changeProvider = (id: number) => {
    setProviderId(id);
    setSelfUnsatisfiedSlug(null);
    setError(null);
  };

  // The public listing carries the guild-addressed login URLs the
  // self-unsatisfied prompt sends the admin through.
  const loginProvidersQuery = useGuildLoginProviders(guildId, {
    enabled: guildId > 0 && guildPostureActive,
  });

  // Completing the required provider's sign-in updates this admin session's
  // satisfied set, after which saving the requirement succeeds.
  const signInWithRequiredProvider = () => {
    const entry = loginProvidersQuery.data?.providers.find((e) => e.slug === selfUnsatisfiedSlug);
    if (!entry) {
      return;
    }
    const next = `${window.location.pathname}${window.location.search}`;
    window.location.href = `${entry.login_url}?next=${encodeURIComponent(next)}`;
  };
  const canSignInWithRequired =
    selfUnsatisfiedSlug != null &&
    loginProvidersQuery.data?.providers.some((e) => e.slug === selfUnsatisfiedSlug);

  // The guild's shareable sign-in URL, built on the server's origin (which is
  // the app's own origin on web, or the configured server on native).
  const { getServerOrigin } = useServer();
  const urlBase = getServerOrigin() ?? window.location.origin;
  const memberLoginUrl = `${urlBase}/guild/${guildId}/login`;
  const copyMemberLoginUrl = async () => {
    try {
      await navigator.clipboard.writeText(memberLoginUrl);
      toast.success(t("guildAuth.shareUrl.copied"));
    } catch (error) {
      console.error(error);
    }
  };

  if (!guildPostureActive) {
    return null;
  }

  return (
    <div className="space-y-6">
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("guildAuth.policy.title")}</CardTitle>
          <CardDescription>{t("guildAuth.policy.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <RadioGroup
            value={policy}
            onValueChange={(value) => changePolicy(value as "open" | "required")}
            className="gap-3"
          >
            <div className="flex items-start gap-3 rounded-md border px-3 py-3">
              <RadioGroupItem id="guild-auth-open" value="open" className="mt-1" />
              <div>
                <Label htmlFor="guild-auth-open" className="font-medium text-base">
                  {t("guildAuth.policy.openLabel")}
                </Label>
                <p className="text-muted-foreground text-sm">{t("guildAuth.policy.openHelp")}</p>
              </div>
            </div>
            <div className="flex items-start gap-3 rounded-md border px-3 py-3">
              <RadioGroupItem
                id="guild-auth-required"
                value="required"
                disabled={eligibleProviders.length === 0}
                className="mt-1"
              />
              <div className="min-w-0 flex-1 space-y-2">
                <Label htmlFor="guild-auth-required" className="font-medium text-base">
                  {t("guildAuth.policy.requiredLabel")}
                </Label>
                <p className="text-muted-foreground text-sm">
                  {t("guildAuth.policy.requiredHelp")}
                </p>
                {eligibleProviders.length === 0 ? (
                  <p className="text-muted-foreground text-sm italic">
                    {t("guildAuth.policy.noProviders")}
                  </p>
                ) : (
                  policy === "required" && (
                    <Select
                      value={providerId != null ? String(providerId) : undefined}
                      onValueChange={(value) => changeProvider(Number(value))}
                    >
                      <SelectTrigger className="w-full sm:w-72">
                        <SelectValue placeholder={t("guildAuth.policy.providerPlaceholder")} />
                      </SelectTrigger>
                      <SelectContent>
                        {eligibleProviders.map((entry) => (
                          <SelectItem key={entry.id} value={String(entry.id)}>
                            {entry.display_name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )
                )}
              </div>
            </div>
          </RadioGroup>

          {selfUnsatisfiedSlug && (
            <Alert>
              <AlertDescription className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <span>
                  {t("guildAuth.policy.selfUnsatisfied", {
                    providerName: selectedProvider?.display_name ?? selfUnsatisfiedSlug,
                  })}
                </span>
                {canSignInWithRequired && (
                  <Button size="sm" onClick={signInWithRequiredProvider}>
                    {t("guildAuth.policy.signInWith", {
                      providerName: selectedProvider?.display_name ?? selfUnsatisfiedSlug,
                    })}
                  </Button>
                )}
              </AlertDescription>
            </Alert>
          )}
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <div className="flex justify-end">
            <Button onClick={save} disabled={!isDirty || !canSave || updatePolicy.isPending}>
              {updatePolicy.isPending ? t("common:submitting") : t("common:save")}
            </Button>
          </div>
        </CardContent>
      </Card>

      <GuildAuthProvidersSection guildId={guildId} />

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("guildAuth.shareUrl.title")}</CardTitle>
          <CardDescription>{t("guildAuth.shareUrl.description")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <code className="min-w-0 flex-1 truncate rounded bg-muted px-2 py-1.5 text-sm">
            {memberLoginUrl}
          </code>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void copyMemberLoginUrl()}
          >
            {t("guildAuth.shareUrl.copy")}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
};
