/**
 * Platform → Authentication: which ways in the deployment permits.
 *
 * Written here and enforced server-side, so what this page does is offer the
 * choice and state what it costs — never decide it.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { LoginMethod, LoginMethodStatus } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  usePlatformAuthSettings,
  useUpdateLoginMethods,
  useUpdateSessionLifetime,
} from "@/hooks/useSettings";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

/** The methods a pending change would withdraw, and who that strands. */
const withdrawalCost = (methods: LoginMethodStatus[], next: LoginMethod[]) =>
  methods
    .filter((m) => m.enabled && !next.includes(m.method))
    .reduce((total, m) => total + m.would_strand, 0);

export const PlatformAuthSection = () => {
  const { t } = useTranslation("settings");
  const query = usePlatformAuthSettings();
  const [pendingMethods, setPendingMethods] = useState<LoginMethod[] | null>(null);

  const updateMethods = useUpdateLoginMethods({
    onSuccess: () => toast.success(t("auth.methods.saved")),
    onError: (err) => toast.error(getErrorMessage(err, "settings:auth.methods.saveError")),
  });
  if (query.isLoading || !query.data) return null;

  const { methods, guilds_requiring_sign_in, session_max_hours } = query.data;
  const enabled = methods.filter((m) => m.enabled).map((m) => m.method);
  const busy = updateMethods.isPending;

  const applyMethods = (next: LoginMethod[], acknowledge?: number) =>
    updateMethods.mutate({
      methods: next,
      ...(acknowledge === undefined ? {} : { acknowledge_stranded: acknowledge }),
    });

  const toggleMethod = (method: LoginMethod, checked: boolean) => {
    const next = checked ? [...enabled, method] : enabled.filter((m) => m !== method);
    // Withdrawing something somebody signs in with is confirmed against the
    // number it affects; adding one, and withdrawing one nobody uses, is not.
    if (withdrawalCost(methods, next) > 0) {
      setPendingMethods(next);
      return;
    }
    applyMethods(next);
  };

  const pendingStrandCount = pendingMethods === null ? 0 : withdrawalCost(methods, pendingMethods);

  return (
    <>
      <SettingsSection title={t("auth.methods.title")} description={t("auth.methods.description")}>
        <div className="space-y-4">
          {methods.map((entry) => {
            // The last permitted way in cannot be withdrawn: the deployment
            // must keep at least one, which the server holds too.
            const isLastEnabled = entry.enabled && enabled.length === 1;
            return (
              <div key={entry.method} className="flex items-start gap-3">
                <Checkbox
                  id={`login-method-${entry.method}`}
                  checked={entry.enabled}
                  disabled={busy || isLastEnabled}
                  onCheckedChange={(checked) => toggleMethod(entry.method, Boolean(checked))}
                  className="mt-0.5"
                />
                <div className="space-y-1">
                  <Label
                    htmlFor={`login-method-${entry.method}`}
                    className="cursor-pointer font-medium"
                  >
                    {t(`auth.methods.${entry.method}.label`)}
                  </Label>
                  <p className="text-muted-foreground text-sm">
                    {t(`auth.methods.${entry.method}.help`)}
                  </p>
                  {isLastEnabled ? (
                    <p className="text-muted-foreground text-xs">
                      {t("auth.methods.lastRemaining")}
                    </p>
                  ) : null}
                  {entry.enabled && entry.would_strand > 0 ? (
                    <p className="text-amber-600 text-xs dark:text-amber-500">
                      {t("auth.methods.wouldStrand", { count: entry.would_strand })}
                    </p>
                  ) : null}
                  {entry.method === "sso" && entry.enabled && guilds_requiring_sign_in > 0 ? (
                    <p className="text-amber-600 text-xs dark:text-amber-500">
                      {t("auth.methods.guildsRequire", {
                        count: guilds_requiring_sign_in,
                      })}
                    </p>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      </SettingsSection>

      <SessionLifetimeSection hours={session_max_hours ?? null} />

      <ConfirmDialog
        open={pendingMethods !== null}
        onOpenChange={(open) => !open && setPendingMethods(null)}
        title={t("auth.methods.confirmTitle")}
        description={t("auth.methods.confirmBody", { count: pendingStrandCount })}
        confirmLabel={t("auth.methods.confirmAction")}
        destructive
        isLoading={updateMethods.isPending}
        onConfirm={() => {
          if (pendingMethods) applyMethods(pendingMethods, pendingStrandCount);
          setPendingMethods(null);
        }}
      />
    </>
  );
};

/**
 * How long somebody may stay signed in before signing in again.
 *
 * A different question from how long a session may be left alone, which the
 * deployment's configuration holds: this one nothing pushes forward. Blank
 * asks for no limit, which is where a self-hosted deployment starts.
 */
const SessionLifetimeSection = ({ hours }: { hours: number | null }) => {
  const { t } = useTranslation(["settings", "common"]);
  const [value, setValue] = useState(hours === null ? "" : String(hours));
  const update = useUpdateSessionLifetime({
    onSuccess: () => toast.success(t("auth.sessionLifetime.saved")),
    onError: (err) => toast.error(getErrorMessage(err, "settings:auth.sessionLifetime.error")),
  });

  const trimmed = value.trim();
  const parsed = trimmed === "" ? null : Number.parseInt(trimmed, 10);
  const valid = parsed === null || (Number.isFinite(parsed) && parsed >= 1);
  const changed = (hours === null ? "" : String(hours)) !== trimmed;

  return (
    <SettingsSection
      title={t("auth.sessionLifetime.title")}
      description={t("auth.sessionLifetime.description")}
    >
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor="session-max-hours">{t("auth.sessionLifetime.label")}</Label>
          <Input
            id="session-max-hours"
            type="number"
            min={1}
            className="w-40"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={t("auth.sessionLifetime.placeholder")}
          />
        </div>
        <Button
          disabled={!valid || !changed || update.isPending}
          onClick={() => update.mutate({ session_max_hours: parsed })}
        >
          {update.isPending ? t("common:submitting") : t("common:save")}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">{t("auth.sessionLifetime.hint")}</p>
    </SettingsSection>
  );
};
