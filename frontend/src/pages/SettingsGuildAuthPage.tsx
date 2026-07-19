import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
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
  useLoginProviders,
  useUpdateGuildAuthPolicy,
} from "@/hooks/useGuildAuthPolicy";
import { useInterfaceSettings } from "@/hooks/useSettings";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

/**
 * Guild sign-in requirement (Settings → Authentication). A guild admin can
 * require that sessions reach this guild only after signing in through one
 * specific SSO provider; `open` (the default) admits any signed-in session.
 * The provider list is the operator-global login registry — only entries the
 * login page itself would offer are eligible.
 */
export const SettingsGuildAuthPage = () => {
  const { t } = useTranslation(["settings", "common"]);
  const guildId = useActiveGuildId();

  const policyQuery = useGuildAuthPolicy(guildId);
  const providersQuery = useLoginProviders();
  // Only registry-backed entries can be required (the policy stores the
  // provider's id); an id-less platform entry means it hasn't reconciled yet.
  const eligibleProviders = useMemo(
    () => (providersQuery.data?.providers ?? []).filter((entry) => entry.id != null),
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

  // Completing the required provider's sign-in updates this admin session's
  // satisfied set, after which saving the requirement succeeds.
  const signInWithRequiredProvider = () => {
    const entry = eligibleProviders.find((e) => e.slug === selfUnsatisfiedSlug);
    if (!entry) {
      return;
    }
    const next = `${window.location.pathname}${window.location.search}`;
    window.location.href = `${entry.login_url}?next=${encodeURIComponent(next)}`;
  };

  // The per-guild provider registry is a separate, still-upcoming posture;
  // its placeholder only shows on servers configured for per-guild login.
  const interfaceSettings = useInterfaceSettings();
  const guildPostureActive = interfaceSettings.data?.auth_scope === "guild";

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
            onValueChange={(value) => setPolicy(value as "open" | "required")}
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
                      onValueChange={(value) => setProviderId(Number(value))}
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
                <Button size="sm" onClick={signInWithRequiredProvider}>
                  {t("guildAuth.policy.signInWith", {
                    providerName: selectedProvider?.display_name ?? selfUnsatisfiedSlug,
                  })}
                </Button>
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

      {guildPostureActive && (
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              {t("guildAuth.title")}
              <Badge variant="secondary">{t("guildAuth.comingSoon")}</Badge>
            </CardTitle>
            <CardDescription>{t("guildAuth.description")}</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground text-sm">{t("guildAuth.body")}</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
};
