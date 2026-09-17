import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { GuildAuthProvidersSection } from "@/components/auth/GuildAuthProvidersSection";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import {
  useGuildAuthPolicy,
  useGuildAuthProviders,
  useGuildAuthSettings,
  useGuildLoginProviders,
  useUpdateGuildApiAccess,
  useUpdateGuildAuthPolicy,
  useUpdateGuildSessionLimit,
} from "@/hooks/useGuildAuthPolicy";
import { useGuilds } from "@/hooks/useGuilds";
import { useServer } from "@/hooks/useServer";
import { useServerForm } from "@/hooks/useServerForm";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

/**
 * Guild sign-in configuration (Settings → Authentication): the guild's own
 * identity provider registry, and the sign-in requirement a guild admin can
 * set against it — sessions reach this guild only after signing in through
 * one specific provider; `open` (the default) admits any signed-in session.
 */
/** The select's value for "any of ours" — a requirement that names no single
 * provider. Not a number, so it can never collide with a provider id. */
const ANY_PROVIDER = "any";

/**
 * The state behind a switch that saves as it is flipped rather than waiting
 * for a button. The draft is what the switch shows until the refreshed guild
 * list carries the saved value; a failed save drops it and keeps a message.
 */
const useFlipToSave = (saved: boolean, guildId: number) => {
  const [state, setState] = useState<{
    guildId: number;
    draft: boolean | null;
    error: string | null;
  }>({ guildId, draft: null, error: null });
  const current = state.guildId === guildId ? state : { guildId, draft: null, error: null };
  return {
    value: current.draft ?? saved,
    error: current.error,
    begin: (next: boolean) => {
      setState({ guildId, draft: next, error: null });
    },
    settle: () => {
      setState((previous) =>
        previous.guildId === guildId ? { guildId, draft: null, error: null } : previous
      );
    },
    fail: (message: string) => {
      setState((previous) =>
        previous.guildId === guildId ? { guildId, draft: null, error: message } : previous
      );
    },
  };
};

export const SettingsGuildAuthPage = () => {
  const { t } = useTranslation(["settings", "common"]);
  const guildId = useActiveGuildId();

  // What the operator has granted this guild. Each section hangs off its own
  // grant: editing the provider list needs ``providers``, the sign-in
  // requirement needs ``require_sign_in``. Outside both the tab is hidden and a
  // direct URL renders nothing (fail closed while still loading).
  const { activeGuild, refreshGuilds } = useGuilds();
  const hasGrantedSeat = activeGuild?.grantSettingsLevel === "superadmin";
  const authSettingsQuery = useGuildAuthSettings(guildId, {
    enabled: guildId > 0 && hasGrantedSeat,
  });
  const authSettings = hasGrantedSeat ? authSettingsQuery.data : undefined;
  const grantedOptions = authSettings?.auth_options ?? activeGuild?.auth_options ?? [];
  const mayConfigureProviders = grantedOptions.includes("providers");
  const mayRequireSignIn = grantedOptions.includes("require_sign_in");
  // The seat above admin holds a community's sign-in configuration, and this
  // page is all of it — so it is theirs to reach, not only theirs to write.
  // The tab is gated the same way; this is the direct-URL half.
  const isSuperadmin = activeGuild?.role === "superadmin" || hasGrantedSeat;
  const guildPostureActive = mayConfigureProviders || mayRequireSignIn;

  const policyQuery = useGuildAuthPolicy(guildId, {
    enabled: guildId > 0 && mayRequireSignIn,
  });
  // Read for either grant. A requirement names one of the guild's providers, so
  // choosing one needs the list even where editing it is not on offer — the two
  // grants are independent and a guild may hold only the requirement half.
  const providersQuery = useGuildAuthProviders(guildId, {
    enabled: guildId > 0 && guildPostureActive,
  });
  // Only the guild's enabled providers can be required — a disabled row can't
  // serve a sign-in, so requiring it would lock the guild.
  const eligibleProviders = useMemo(
    () => (providersQuery.data ?? []).filter((entry) => entry.enabled),
    [providersQuery.data]
  );

  // Chosen here, saved by the button below — a refetch in between must not
  // undo the choice.
  const form = useServerForm(
    policyQuery.data,
    (loaded) => ({
      policy: loaded?.policy ?? ("open" as "open" | "required"),
      providerId: loaded?.provider_id ?? null,
      // A rule that names no provider and asks for the community's own
      // single sign-on is the "any of ours" choice below.
      anyProvider: loaded?.provider_id == null && (loaded?.require_methods ?? []).includes("sso"),
      // Orthogonal to the provider choice: a community may ask for its own
      // sign-in, for a second factor, or for both.
      requireFactor: (loaded?.require_methods ?? []).includes("totp"),
    }),
    guildId
  );
  const { policy, providerId, anyProvider, requireFactor } = form.values;
  const setPolicy = (next: "open" | "required") => form.set({ policy: next });
  const [error, setError] = useState<string | null>(null);
  const [selfUnsatisfiedSlug, setSelfUnsatisfiedSlug] = useState<string | null>(null);

  const updatePolicy = useUpdateGuildAuthPolicy(guildId);

  // Each of these is one boolean, so both save as they are switched.
  const updateApiAccess = useUpdateGuildApiAccess(guildId);
  const apiAccess = useFlipToSave(
    authSettings?.allow_api_keys ?? activeGuild?.allow_api_keys ?? true,
    guildId
  );

  const changeApiAccess = (next: boolean) => {
    apiAccess.begin(next);
    updateApiAccess.mutate(
      { allow_api_keys: next },
      {
        onSuccess: async () => {
          if (hasGrantedSeat) {
            await authSettingsQuery.refetch();
          } else {
            await refreshGuilds();
          }
          apiAccess.settle();
          toast.success(t("guildAuth.apiAccess.saved"));
        },
        onError: (err: unknown) => {
          apiAccess.fail(getErrorMessage(err, "settings:guildAuth.apiAccess.error"));
        },
      }
    );
  };

  const updateSessionLimit = useUpdateGuildSessionLimit(guildId);
  const sessionLimit = useFlipToSave(
    authSettings?.enforce_compliance_session ?? activeGuild?.enforce_compliance_session ?? false,
    guildId
  );

  const changeSessionLimit = (next: boolean) => {
    sessionLimit.begin(next);
    updateSessionLimit.mutate(
      { enforce_compliance_session: next },
      {
        onSuccess: async () => {
          if (hasGrantedSeat) {
            await authSettingsQuery.refetch();
          } else {
            await refreshGuilds();
          }
          sessionLimit.settle();
          toast.success(t("guildAuth.sessionLimit.saved"));
        },
        onError: (err: unknown) => {
          sessionLimit.fail(getErrorMessage(err, "settings:guildAuth.sessionLimit.error"));
        },
      }
    );
  };

  const selectedProvider = eligibleProviders.find((entry) => entry.id === providerId);
  const savedAnyProvider =
    policyQuery.data != null &&
    policyQuery.data.provider_id == null &&
    (policyQuery.data.require_methods ?? []).includes("sso");
  const savedRequireFactor =
    policyQuery.data != null && (policyQuery.data.require_methods ?? []).includes("totp");
  const isDirty =
    policyQuery.data != null &&
    (policy !== policyQuery.data.policy ||
      (policy === "required" &&
        (anyProvider !== savedAnyProvider ||
          requireFactor !== savedRequireFactor ||
          (!anyProvider && providerId !== (policyQuery.data.provider_id ?? null)))));
  // A rule has to ask for something. Any one of the three will do.
  const canSave = policy === "open" || anyProvider || requireFactor || providerId != null;

  const save = () => {
    // What is being sent, so a choice changed while this is in flight is not
    // counted as saved by it.
    const sent = form.values;
    updatePolicy.mutate(
      policy === "open"
        ? { policy: "open" }
        : {
            policy: "required",
            ...(anyProvider ? {} : { provider_id: providerId as number }),
            require_methods: [
              ...(anyProvider ? (["sso"] as const) : []),
              ...(requireFactor ? (["totp"] as const) : []),
            ],
          },
      {
        onSuccess: () => {
          setError(null);
          setSelfUnsatisfiedSlug(null);
          form.settle(sent);
          toast.success(t("guildAuth.policy.saved"));
        },
        onError: (err: unknown) => {
          const detail = (err as { response?: { data?: { detail?: string } } }).response?.data
            ?.detail;
          if (detail === "GUILD_AUTH_POLICY_SELF_UNSATISFIED") {
            // "Any of ours" is satisfied by any of them, so offer the first.
            const chosen = anyProvider
              ? eligibleProviders[0]
              : eligibleProviders.find((entry) => entry.id === providerId);
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
  const changeProvider = (value: string) => {
    form.set(
      value === ANY_PROVIDER
        ? { anyProvider: true, providerId: null }
        : { anyProvider: false, providerId: Number(value) }
    );
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
  const memberLoginUrl = `${urlBase}/community/${guildId}/login`;
  const copyMemberLoginUrl = async () => {
    try {
      await navigator.clipboard.writeText(memberLoginUrl);
      toast.success(t("guildAuth.shareUrl.copied"));
    } catch (error) {
      console.error(error);
    }
  };

  if (!isSuperadmin || (hasGrantedSeat && authSettings == null)) {
    return null;
  }

  return (
    <div className="space-y-6">
      {mayRequireSignIn ? (
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
                        value={
                          anyProvider
                            ? ANY_PROVIDER
                            : providerId != null
                              ? String(providerId)
                              : undefined
                        }
                        onValueChange={changeProvider}
                      >
                        <SelectTrigger className="w-full sm:w-72">
                          <SelectValue placeholder={t("guildAuth.policy.providerPlaceholder")} />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value={ANY_PROVIDER}>
                            {t("guildAuth.policy.anyProvider")}
                          </SelectItem>
                          {eligibleProviders.map((entry) => (
                            <SelectItem key={entry.id} value={String(entry.id)}>
                              {entry.display_name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )
                  )}
                  {policy === "required" && anyProvider && (
                    <p className="text-muted-foreground text-sm">
                      {t("guildAuth.policy.anyProviderHelp")}
                    </p>
                  )}
                </div>
              </div>
            </RadioGroup>

            {policy === "required" && (
              <div className="flex items-start gap-3 border-t pt-4">
                <Checkbox
                  id="require-second-factor"
                  checked={requireFactor}
                  onCheckedChange={(checked) => form.set({ requireFactor: Boolean(checked) })}
                />
                <div className="space-y-1">
                  <Label htmlFor="require-second-factor" className="font-medium">
                    {t("guildAuth.policy.requireFactor")}
                  </Label>
                  <p className="text-muted-foreground text-sm">
                    {t("guildAuth.policy.requireFactorHelp")}
                  </p>
                </div>
              </div>
            )}

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
      ) : null}

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("guildAuth.apiAccess.title")}</CardTitle>
          <CardDescription>{t("guildAuth.apiAccess.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <Label htmlFor="guild-allow-api-keys" className="font-medium">
                {t("guildAuth.apiAccess.allowLabel")}
              </Label>
              <p className="text-muted-foreground text-sm">
                {apiAccess.value
                  ? t("guildAuth.apiAccess.allowHelp")
                  : t("guildAuth.apiAccess.blockedHelp")}
              </p>
            </div>
            <Switch
              id="guild-allow-api-keys"
              checked={apiAccess.value}
              onCheckedChange={changeApiAccess}
              disabled={updateApiAccess.isPending}
            />
          </div>
          {apiAccess.error && (
            <Alert variant="destructive">
              <AlertDescription>{apiAccess.error}</AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("guildAuth.sessionLimit.title")}</CardTitle>
          <CardDescription>{t("guildAuth.sessionLimit.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <Label htmlFor="guild-session-limit" className="font-medium">
                {t("guildAuth.sessionLimit.allowLabel")}
              </Label>
              <p className="text-muted-foreground text-sm">
                {sessionLimit.value
                  ? t("guildAuth.sessionLimit.onHelp")
                  : t("guildAuth.sessionLimit.offHelp")}
              </p>
            </div>
            <Switch
              id="guild-session-limit"
              checked={sessionLimit.value}
              onCheckedChange={changeSessionLimit}
              disabled={updateSessionLimit.isPending}
            />
          </div>
          {sessionLimit.error && (
            <Alert variant="destructive">
              <AlertDescription>{sessionLimit.error}</AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      {mayConfigureProviders ? <GuildAuthProvidersSection guildId={guildId} /> : null}

      {guildPostureActive ? (
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
      ) : null}
    </div>
  );
};
