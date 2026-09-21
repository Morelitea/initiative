import { useTranslation } from "react-i18next";

import { SettingsSection } from "@/components/settings/SettingsSection";
import { Button } from "@/components/ui/button";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useConsent } from "@/hooks/useConsent";
import { useServer } from "@/hooks/useServer";
import { OPTIONAL_CONSENT_CATEGORIES, reopenConsent } from "@/lib/consent";

/**
 * What this browser is currently allowing, and the way to change it.
 *
 * Here because a landing-page footer is no use to somebody already signed in
 * and three pages deep, and taking an answer back has to stay as easy as
 * giving one. It reads the browser rather than the account: the answer was
 * given by a browser and applies to that browser, so signing in on a second
 * one asks again rather than inheriting a decision made somewhere else.
 */
export const CookieChoicesSection = () => {
  const { t } = useTranslation(["settings", "legal"]);
  const { isNativePlatform } = useServer();
  const { cookieConsentEnabled } = useAppConfig();
  const { unanswered, granted } = useConsent();

  if (isNativePlatform || !cookieConsentEnabled) {
    return null;
  }

  const allowed = OPTIONAL_CONSENT_CATEGORIES.filter((category) => granted.includes(category));

  return (
    <SettingsSection title={t("settings:privacy.cookies.title")}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <p className="max-w-prose text-muted-foreground text-sm">
            {unanswered
              ? t("settings:privacy.cookies.unanswered")
              : allowed.length === 0
                ? t("settings:privacy.cookies.noneAllowed")
                : t("settings:privacy.cookies.allowed", {
                    categories: allowed
                      .map((category) => t(`legal:cookies.categories.${category}.name`))
                      .join(", "),
                  })}
          </p>
          <p className="max-w-prose text-muted-foreground text-xs">
            {t("settings:privacy.cookies.perBrowser")}
          </p>
        </div>
        <Button variant="outline" onClick={reopenConsent} className="shrink-0">
          {t("settings:privacy.cookies.change")}
        </Button>
      </div>
    </SettingsSection>
  );
};
