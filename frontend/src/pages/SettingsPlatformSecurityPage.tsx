/**
 * Platform → Security.
 *
 * What the deployment asks of everybody's sign-in, rather than how anybody
 * signs in — that is Authentication, next door. Two questions so far: how long
 * a session may last, and who has to hold a second factor.
 */

import { useTranslation } from "react-i18next";

import { SecondFactorMethodSection } from "@/components/admin/SecondFactorMethodSection";
import { SecondFactorRequirementSection } from "@/components/admin/SecondFactorRequirementSection";
import { SessionLifetimeSection } from "@/components/admin/SessionLifetimeSection";
import { useAuth } from "@/hooks/useAuth";
import { Capability, hasCapability } from "@/lib/permissions";

export const SettingsPlatformSecurityPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();

  if (!hasCapability(user, Capability.configManage)) {
    return <p className="text-muted-foreground text-sm">{t("auth.adminOnly")}</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-semibold text-2xl tracking-tight">{t("platformSecurity.title")}</h2>
        <p className="text-muted-foreground text-sm">{t("platformSecurity.description")}</p>
      </div>
      <SessionLifetimeSection />
      {/* Offered first, then required: a rule needs something to answer it. */}
      <SecondFactorMethodSection />
      <SecondFactorRequirementSection />
    </div>
  );
};
