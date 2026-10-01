/**
 * The frame every front-door page sits in: a header that is always there,
 * with the same few places in it (Download, Pricing where plans are sold,
 * the docs, signing in and up), and a footer that lists the rest.
 *
 * On a phone the places fold into a menu under the header, and signing up
 * stays beside it as the one button.
 */

import { Link } from "@tanstack/react-router";
import { ArrowRight, ArrowUpRight, Menu, X } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import { LogoIcon } from "@/components/LogoIcon";
import { ModeToggle } from "@/components/ModeToggle";
import { Button } from "@/components/ui/button";
import { reopenConsent } from "@/lib/consent";
import { CHANGELOG_URL, DOCS_URL, docsUrl, REPO_URL } from "@/lib/links";
import { cn } from "@/lib/utils";

import { LANDING_KEYFRAMES } from "./effects";
import { useFrontDoor } from "./useFrontDoor";

type Place = "download" | "pricing";

const navLink =
  "inline-flex min-h-11 items-center rounded-lg px-3.5 font-medium text-foreground/80 hover:bg-muted hover:text-foreground";

const Header = ({ current }: { current?: Place }) => {
  const { t } = useTranslation("landing");
  const { registrationOpen, showsPricing } = useFrontDoor();
  const [open, setOpen] = useState(false);

  const places: { key: Place; to: string; label: string }[] = [
    { key: "download", to: "/download", label: t("nav.download") },
    ...(showsPricing ? [{ key: "pricing" as const, to: "/pricing", label: t("nav.pricing") }] : []),
  ];

  return (
    <header className="sticky top-0 z-50 border-b bg-background/90 backdrop-blur-xl">
      <div className="mx-auto flex h-15 max-w-6xl items-center justify-between gap-4 px-4 md:h-17 md:px-8">
        <Link
          to="/welcome"
          className="flex items-center gap-2.5 font-bold text-foreground text-xl tracking-tight md:text-2xl"
          aria-label={t("nav.home")}
        >
          <LogoIcon className="h-8 w-8" aria-hidden="true" />
          <span className="pride-wordmark">initiative</span>
        </Link>
        <div className="flex items-center gap-1.5">
          <nav className="mr-2 hidden items-center gap-0.5 md:flex" aria-label={t("nav.mainAria")}>
            {places.map((place) => (
              <Link
                key={place.key}
                to={place.to}
                className={cn(navLink, current === place.key && "bg-muted text-foreground")}
                aria-current={current === place.key ? "page" : undefined}
              >
                {place.label}
              </Link>
            ))}
            <a href={DOCS_URL} target="_blank" rel="noopener noreferrer" className={navLink}>
              {t("nav.docs")}
            </a>
            {registrationOpen ? (
              <Link to="/login" search={true} className={navLink}>
                {t("nav.signIn")}
              </Link>
            ) : null}
          </nav>
          <div className="hidden md:block">
            <ModeToggle />
          </div>
          <Button asChild>
            {registrationOpen ? (
              <Link to="/start">{t("nav.signUp")}</Link>
            ) : (
              <Link to="/login" search={true}>
                {t("nav.signIn")}
              </Link>
            )}
          </Button>
          <Button
            variant="outline"
            size="icon"
            className="h-11 w-11 md:hidden"
            aria-label={t("nav.menu")}
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </Button>
        </div>
      </div>
      {open ? (
        <nav className="border-t px-4 pt-2 pb-4 md:hidden" aria-label={t("nav.mainAria")}>
          {places.map((place) => (
            <Link
              key={place.key}
              to={place.to}
              className="flex min-h-14 items-center justify-between border-b font-semibold text-lg"
            >
              {place.label}
              <ArrowRight className="h-5 w-5" aria-hidden="true" />
            </Link>
          ))}
          <a
            href={DOCS_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="flex min-h-14 items-center justify-between border-b font-semibold text-lg"
          >
            {t("nav.docs")}
            <ArrowUpRight className="h-5 w-5" aria-hidden="true" />
          </a>
          {registrationOpen ? (
            <Link
              to="/login"
              search={true}
              className="flex min-h-14 items-center justify-between font-semibold text-lg"
            >
              {t("nav.signIn")}
              <ArrowRight className="h-5 w-5" aria-hidden="true" />
            </Link>
          ) : null}
          <div className="flex justify-end pt-3">
            <ModeToggle />
          </div>
        </nav>
      ) : null}
    </header>
  );
};

const footerLink =
  "inline-flex min-h-9 items-center text-muted-foreground text-sm hover:text-foreground";

const External = ({ href, children }: { href: string; children: ReactNode }) => (
  <a href={href} target="_blank" rel="noopener noreferrer" className={footerLink}>
    {children}
  </a>
);

const Footer = () => {
  const { t } = useTranslation("landing");
  const { showsPricing, cookieConsentEnabled } = useFrontDoor();

  return (
    <footer className="border-t">
      <div className="mx-auto max-w-6xl px-4 pt-14 pb-10 md:px-8">
        <div className="grid grid-cols-2 gap-6 md:grid-cols-[2fr_1fr_1fr_1fr] md:gap-8">
          <div className="col-span-2 md:col-span-1">
            <div className="flex items-center gap-2.5 font-bold text-foreground text-xl">
              <LogoIcon className="h-7 w-7" aria-hidden="true" />
              <span className="pride-wordmark">initiative</span>
            </div>
            <p className="mt-3 max-w-xs text-muted-foreground text-sm">{t("footer.tagline")}</p>
          </div>
          <div>
            <h2 className="mb-2 font-bold text-sm">{t("footer.getIt")}</h2>
            <ul>
              <li>
                <Link to="/download" className={footerLink}>
                  {t("footer.download")}
                </Link>
              </li>
              {showsPricing ? (
                <li>
                  <Link to="/pricing" className={footerLink}>
                    {t("footer.pricing")}
                  </Link>
                </li>
              ) : null}
              <li>
                <External href={CHANGELOG_URL}>{t("footer.changelog")}</External>
              </li>
            </ul>
          </div>
          <div>
            <h2 className="mb-2 font-bold text-sm">{t("footer.docs")}</h2>
            <ul>
              <li>
                <External href={docsUrl("getting-started/")}>{t("footer.gettingStarted")}</External>
              </li>
              <li>
                <External href={docsUrl("faq/")}>{t("footer.faq")}</External>
              </li>
              <li>
                <External href={docsUrl("running-a-server/")}>{t("footer.server")}</External>
              </li>
              <li>
                <External href={docsUrl("security/")}>{t("footer.security")}</External>
              </li>
            </ul>
          </div>
          <div>
            <h2 className="mb-2 font-bold text-sm">{t("footer.project")}</h2>
            <ul>
              <li>
                <External href={REPO_URL}>{t("footer.source")}</External>
              </li>
              {/* Taking an answer back has to be as easy as giving one, and a
                  front-door reader has no settings page to go to. Only where
                  the deployment asks the question at all. */}
              {cookieConsentEnabled ? (
                <li>
                  <button type="button" onClick={reopenConsent} className={footerLink}>
                    {t("footer.cookies")}
                  </button>
                </li>
              ) : null}
            </ul>
          </div>
        </div>
        <p className="mt-10 text-muted-foreground text-sm">
          {t("footer.copyright", { year: new Date().getFullYear() })}
        </p>
      </div>
    </footer>
  );
};

export const LandingShell = ({ current, children }: { current?: Place; children: ReactNode }) => (
  <div className="min-h-screen overflow-x-clip bg-background text-foreground">
    <style>{LANDING_KEYFRAMES}</style>
    <Header current={current} />
    <main>{children}</main>
    <Footer />
  </div>
);
