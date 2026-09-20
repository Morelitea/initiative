/**
 * Platform → Security: which second factors this server offers.
 *
 * A second factor accompanies a sign-in rather than opening one, so it is not
 * one of the ways in — it belongs beside the rule that asks for it. Which
 * methods land here is the server's own `primary` flag, so a method added
 * later arrives in the right place without a list to update.
 *
 * No acknowledgement dialog, unlike the ways in: withdrawing a second factor
 * strands nobody, because it was never anybody's only way to sign in. What it
 * can do is leave a standing requirement with nothing to answer it, and the
 * server refuses that with its own message.
 */

import { useTranslation } from "react-i18next";

import type { LoginMethod } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { usePlatformAuthSettings, useUpdateLoginMethods } from "@/hooks/useSettings";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

export const SecondFactorMethodSection = () => {
  const { t } = useTranslation("settings");
  const query = usePlatformAuthSettings();

  const updateMethods = useUpdateLoginMethods({
    onSuccess: () => toast.success(t("auth.factorMethods.saved")),
    onError: (err) => toast.error(getErrorMessage(err, "settings:auth.factorMethods.saveError")),
  });

  if (query.isLoading || !query.data) return null;

  const { methods } = query.data;
  const factors = methods.filter((entry) => !entry.primary);
  if (factors.length === 0) return null;

  const enabled = methods.filter((m) => m.enabled).map((m) => m.method);
  const busy = updateMethods.isPending;

  const toggleMethod = (method: LoginMethod, checked: boolean) =>
    updateMethods.mutate({
      methods: checked ? [...enabled, method] : enabled.filter((m) => m !== method),
    });

  return (
    <SettingsSection
      title={t("auth.factorMethods.title")}
      description={t("auth.factorMethods.description")}
    >
      <div className="space-y-4">
        {factors.map((entry) => (
          <div key={entry.method} className="flex items-start gap-3">
            <Checkbox
              id={`factor-method-${entry.method}`}
              checked={entry.enabled}
              disabled={busy}
              onCheckedChange={(checked) => toggleMethod(entry.method, Boolean(checked))}
              className="mt-0.5"
            />
            <div className="space-y-1">
              <Label
                htmlFor={`factor-method-${entry.method}`}
                className="cursor-pointer font-medium"
              >
                {t(`auth.methods.${entry.method}.label`)}
              </Label>
              <p className="text-muted-foreground text-sm">
                {t(`auth.methods.${entry.method}.help`)}
              </p>
            </div>
          </div>
        ))}
      </div>
    </SettingsSection>
  );
};
