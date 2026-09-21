import { useState } from "react";
import { useTranslation } from "react-i18next";

import { DocumentLink } from "@/components/auth/LegalNotice";
import { Button } from "@/components/ui/button";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useLegalIndex } from "@/hooks/useLegalDocuments";
import { useServer } from "@/hooks/useServer";
import { captchaProvider } from "@/lib/captchaProviders";
import { acknowledgeCookieNotice, cookieNoticeSeen } from "@/lib/cookieNotice";
import { COOKIE_NOTICE_DOCS_URL } from "@/lib/links";

/**
 * What Initiative keeps in this browser, said once to somebody who has just
 * arrived.
 *
 * It acknowledges rather than asks. Everything stored here is needed to run
 * what the reader came for — staying signed in, their theme, what they had
 * open — and there is no advertising, no analytics and nothing following
 * anybody between sites, so there is no choice to offer and a Reject button
 * would be a button that does nothing. Where an operator has put a spam check
 * in front of sign-up, that vendor is the one third party there is, and the
 * notice names them.
 *
 * Off unless the deployment turned it on (``cookie_notice_enabled``), because
 * most deployments are a group's own server reached by people who were sent a
 * link, and a notice nobody needed is just something in the way.
 *
 * Mounted once at the root, like the step-up dialogs: somebody's first arrival
 * is as likely to be an invite link or the sign-in page as the landing page.
 * It blocks nothing and takes no focus — the reader can ignore it and carry
 * on, which is the other half of not asking them anything.
 */
export const CookieNotice = () => {
  const { t } = useTranslation(["legal", "common"]);
  const { isNativePlatform } = useServer();
  const { captcha, cookieNoticeEnabled, isLoading } = useAppConfig();
  const { enabled: hasLegalDocuments } = useLegalIndex();
  const [acknowledged, setAcknowledged] = useState(cookieNoticeSeen);

  // The app store's own disclosures cover the installed app, and there is no
  // site to have landed on.
  if (isNativePlatform || acknowledged || isLoading || !cookieNoticeEnabled) {
    return null;
  }

  const spamCheck = captcha ? captchaProvider(captcha.provider) : undefined;

  const acknowledge = () => {
    acknowledgeCookieNotice();
    setAcknowledged(true);
  };

  return (
    // The strip itself takes no pointer events, so the page underneath is
    // still usable either side of the card.
    <div
      className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex justify-center p-4"
      style={{ paddingBottom: "calc(1rem + var(--safe-area-inset-bottom))" }}
    >
      <section
        aria-label={t("legal:cookies.label")}
        className="pointer-events-auto flex w-full max-w-3xl flex-col gap-4 rounded-lg border bg-background/95 p-4 shadow-lg backdrop-blur supports-[backdrop-filter]:bg-background/85 sm:flex-row sm:items-center"
      >
        <div className="min-w-0 flex-1 space-y-1">
          <p className="font-medium text-sm">{t("legal:cookies.title")}</p>
          <p className="text-muted-foreground text-sm">
            {t("legal:cookies.body", { appName: t("common:appName") })}
          </p>
          {spamCheck ? (
            <p className="text-muted-foreground text-sm">
              {t("legal:cookies.spamCheck", { provider: spamCheck.name })}
            </p>
          ) : null}
          <p className="flex flex-wrap items-center gap-x-4 gap-y-1 pt-1 text-sm">
            <a
              href={COOKIE_NOTICE_DOCS_URL}
              target="_blank"
              rel="noreferrer"
              className="text-primary underline-offset-4 hover:underline"
            >
              {t("legal:cookies.readMore")}
            </a>
            {/* Only where the deployment has a policy of its own to read. */}
            {hasLegalDocuments ? (
              <DocumentLink slug="privacy">{t("legal:privacyTitle")}</DocumentLink>
            ) : null}
          </p>
        </div>
        <Button onClick={acknowledge} className="shrink-0 sm:self-center">
          {t("legal:cookies.acknowledge")}
        </Button>
      </section>
    </div>
  );
};
