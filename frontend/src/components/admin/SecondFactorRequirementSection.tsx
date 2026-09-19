/**
 * Platform → Security: who this deployment asks to hold a second factor.
 *
 * Three answers and one save. What satisfies it is the account holding a
 * factor — an authenticator or a passkey — or a session that presented one,
 * which is what an identity provider's own second factor looks like from
 * here.
 *
 * Written here and enforced server-side, so what this page does is offer the
 * choice and state what it costs — never decide it.
 */

import { isAxiosError } from "axios";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { AUTH_FACTOR_REQUIRED_EVENT, type FactorChallengeDetail } from "@/api/client";
import type { SecondFactorRequirement } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { usePlatformAuthSettings, useUpdateSecondFactorRequirement } from "@/hooks/useSettings";
import { toast } from "@/lib/chesterToast";
import { getErrorCode, getErrorMessage } from "@/lib/errorMessage";

/** The three answers, in the order they widen. */
const LEVELS = ["nobody", "platform_roles", "everyone"] as const;

export const SecondFactorRequirementSection = () => {
  const query = usePlatformAuthSettings();
  if (query.isLoading || !query.data) return null;

  // Mounted once the stored answer is known, so the choice is not reset
  // underneath whoever is reading it.
  return (
    <SecondFactorRequirementForm
      saved={query.data.second_factor_requirement}
      withoutFactor={query.data.accounts_without_factor}
    />
  );
};

const SecondFactorRequirementForm = ({
  saved,
  withoutFactor,
}: {
  saved: SecondFactorRequirement;
  withoutFactor: { platform_roles: number; everyone: number };
}) => {
  const { t } = useTranslation(["settings", "common"]);
  const [choice, setChoice] = useState<SecondFactorRequirement>(saved);
  /** Set when the server refuses because this account does not meet the rule
   *  itself. Answered where they stand, by the dialog every refusal opens. */
  const [unmet, setUnmet] = useState(false);

  const update = useUpdateSecondFactorRequirement({
    onSuccess: () => {
      setUnmet(false);
      toast.success(t("auth.secondFactorRequirement.saved"));
    },
    onError: (err) => {
      if (
        isAxiosError(err) &&
        getErrorCode(err) === "SETTINGS_FACTOR_REQUIREMENT_SELF_UNSATISFIED"
      ) {
        setUnmet(true);
        return;
      }
      setUnmet(false);
      toast.error(getErrorMessage(err, "settings:auth.secondFactorRequirement.error"));
    },
  });

  const change = (next: SecondFactorRequirement) => {
    setChoice(next);
    setUnmet(false);
  };

  /** How many accounts the chosen answer would ask to set one up. */
  const wouldAsk =
    choice === "everyone"
      ? withoutFactor.everyone
      : choice === "platform_roles"
        ? withoutFactor.platform_roles
        : 0;

  return (
    <SettingsSection
      title={t("auth.secondFactorRequirement.title")}
      description={t("auth.secondFactorRequirement.description")}
    >
      <RadioGroup
        value={choice}
        onValueChange={(value) => change(value as SecondFactorRequirement)}
        className="gap-3"
      >
        {LEVELS.map((level) => (
          <div key={level} className="flex items-start gap-3 rounded-md border px-3 py-3">
            <RadioGroupItem id={`second-factor-${level}`} value={level} className="mt-1" />
            <div className="space-y-1">
              <Label htmlFor={`second-factor-${level}`} className="font-medium text-base">
                {t(`auth.secondFactorRequirement.levels.${level}.label`)}
              </Label>
              <p className="text-muted-foreground text-sm">
                {t(`auth.secondFactorRequirement.levels.${level}.help`)}
              </p>
            </div>
          </div>
        ))}
      </RadioGroup>

      {wouldAsk > 0 && (
        <p className="text-muted-foreground text-sm">
          {t("auth.secondFactorRequirement.wouldAsk", { count: wouldAsk })}
        </p>
      )}

      {choice !== "nobody" && (
        <p className="text-muted-foreground text-sm">
          {t("auth.secondFactorRequirement.derivedCredentials")}
        </p>
      )}

      {unmet && (
        <Alert>
          <AlertDescription className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <span>{t("auth.secondFactorRequirement.unmet")}</span>
            <Button
              size="sm"
              onClick={() =>
                window.dispatchEvent(
                  new CustomEvent<FactorChallengeDetail>(AUTH_FACTOR_REQUIRED_EVENT, {
                    detail: { guildId: null, kind: "totp" },
                  })
                )
              }
            >
              {t("auth.secondFactorRequirement.present")}
            </Button>
          </AlertDescription>
        </Alert>
      )}

      <div className="flex justify-end">
        <Button
          disabled={choice === saved || update.isPending}
          onClick={() => update.mutate({ level: choice })}
        >
          {update.isPending ? t("common:submitting") : t("common:save")}
        </Button>
      </div>
    </SettingsSection>
  );
};
