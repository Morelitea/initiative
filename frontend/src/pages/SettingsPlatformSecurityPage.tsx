/**
 * Platform → Security.
 *
 * What the deployment asks of everybody's sign-in, rather than how anybody
 * signs in — that is Authentication, next door. Today that is the one question
 * of how long a session may last; this is the tab further answers of the same
 * kind belong on.
 */

import { useTranslation } from "react-i18next";

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
    </div>
  );
};
