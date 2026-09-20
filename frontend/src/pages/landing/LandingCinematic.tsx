/**
 * The front door for somebody who is not signed in.
 *
 * Most people who land here were sent a link by their group, so the page
 * leads with signing in and with what to expect once they're in; starting a
 * community of your own comes second. Plans appear only on a deployment with
 * a billing portal, in the portal's own words; the tools grid is the tool
 * registry, so a new tool shows up here without anybody remembering to add it.
 */

import { Link, useRouter } from "@tanstack/react-router";
import type { ParseKeys } from "i18next";
import type { LucideIcon } from "lucide-react";
import {
  ArrowUpRight,
  BookOpen,
  ChevronDown,
  Code2,
  Compass,
  HelpCircle,
  KeyRound,
  Layers,
  LifeBuoy,
  MousePointerClick,
  ShieldCheck,
  Sparkles,
  Undo2,
  Wrench,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { ToolSketch } from "@/components/initiatives/ToolSkeletons";
import { LogoIcon } from "@/components/LogoIcon";
import { ModeToggle } from "@/components/ModeToggle";
import { Button } from "@/components/ui/button";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useBillingCatalog } from "@/hooks/useBillingCatalog";
import { useTheme } from "@/hooks/useTheme";
import { CHANGELOG_URL, DOCS_URL, docsUrl, REPO_URL } from "@/lib/links";
import { TOOL_ICONS, TOOLS, toolCamelPlural, toolNavLabelKey } from "@/lib/tools";

import { DownloadSection } from "./DownloadSection";
import { FloatingShape, LANDING_KEYFRAMES, reveal, Starfield, useRevealOnScroll } from "./effects";
import { PricingSection } from "./PricingSection";
import { ScreenshotFrame, ScreenshotLightbox } from "./ScreenshotFrame";
import { screenshot } from "./screenshots";

// ---------------------------------------------------------------------------
// Static content lists
// ---------------------------------------------------------------------------

/** The groups that scroll past under the hero, in the order they read best. */
const RIBBON_KEYS = [
  "fete",
  "rota",
  "pta",
  "dnd",
  "shop",
  "band",
  "festival",
  "committee",
  "dayJob",
  "family",
  "bookClub",
  "fiveASide",
] as const;

const INVITED_STEPS: { icon: LucideIcon; key: "step1" | "step2" | "step3" }[] = [
  { icon: KeyRound, key: "step1" },
  { icon: MousePointerClick, key: "step2" },
  { icon: Undo2, key: "step3" },
];

const PRINCIPLES: { icon: LucideIcon; key: "openSource" | "sameApp" | "oneLogin" | "yourData" }[] =
  [
    { icon: Code2, key: "openSource" },
    { icon: Layers, key: "sameApp" },
    { icon: KeyRound, key: "oneLogin" },
    { icon: ShieldCheck, key: "yourData" },
  ];

const DOC_LINKS: {
  icon: LucideIcon;
  key: "gettingStarted" | "tour" | "guides" | "faq" | "admin" | "security";
  path: string;
}[] = [
  { icon: Compass, key: "gettingStarted", path: "getting-started/" },
  { icon: Sparkles, key: "tour", path: "getting-started/a-quick-tour/" },
  { icon: BookOpen, key: "guides", path: "guides/" },
  { icon: HelpCircle, key: "faq", path: "faq/" },
  { icon: Wrench, key: "admin", path: "admin/" },
  { icon: ShieldCheck, key: "security", path: "security/" },
];

const SCREENSHOT_TILTS = [-2, 1.5, -1];

// ---------------------------------------------------------------------------
// Section chrome
// ---------------------------------------------------------------------------

const SectionHeading = ({
  id,
  label,
  title,
  description,
  visible,
}: {
  id: string;
  label: string;
  title: string;
  description?: string;
  visible: boolean;
}) => (
  <div className={`mb-12 text-center transition-all duration-1000 md:mb-16 ${reveal(visible)}`}>
    <span className="mb-4 block font-semibold text-primary text-sm uppercase tracking-[0.2em]">
      {label}
    </span>
    <h2 id={id} className="mb-4 font-bold text-3xl text-foreground tracking-tight md:text-5xl">
      {title}
    </h2>
    {description && (
      <p className="mx-auto max-w-2xl text-lg text-muted-foreground">{description}</p>
    )}
  </div>
);

const surface = (isDark: boolean) => ({
  background: isDark ? "rgba(30, 25, 60, 0.45)" : "rgba(255, 255, 255, 0.7)",
  borderColor: isDark ? "rgba(140, 130, 255, 0.14)" : "rgba(100, 80, 200, 0.1)",
});

const iconWell = (isDark: boolean) => ({
  background: isDark ? "rgba(140, 130, 255, 0.1)" : "rgba(100, 80, 200, 0.06)",
  border: `1px solid ${isDark ? "rgba(140, 130, 255, 0.2)" : "rgba(100, 80, 200, 0.1)"}`,
});

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export const LandingCinematic = () => {
  const { t } = useTranslation("landing");
  const { t: tNav } = useTranslation("nav");
  const { token, loading } = useAuth();
  const { resolvedTheme } = useTheme();
  const { billing, config } = useAppConfig();
  // Owned here rather than inside the section: the header only offers Pricing
  // once there is a price book to scroll to.
  const catalog = useBillingCatalog(billing?.url);
  const router = useRouter();
  const [publicRegistrationEnabled, setPublicRegistrationEnabled] = useState<boolean | null>(null);
  const [scrollY, setScrollY] = useState(0);
  const [navSolid, setNavSolid] = useState(false);
  const [lightbox, setLightbox] = useState<{ src: string; alt: string } | null>(null);

  const isDark = resolvedTheme === "dark";
  const registrationOpen = publicRegistrationEnabled !== false;

  // Somebody already signed in has no business on the front door.
  useEffect(() => {
    if (!loading && token) {
      router.navigate({ to: "/", replace: true });
    }
  }, [token, loading, router]);

  useEffect(() => {
    const fetchBootstrapStatus = async () => {
      try {
        const response = await apiClient.get<{
          has_users: boolean;
          public_registration_enabled: boolean;
        }>("/auth/bootstrap");
        setPublicRegistrationEnabled(response.data.public_registration_enabled);
      } catch {
        setPublicRegistrationEnabled(true);
      }
    };
    void fetchBootstrapStatus();
  }, []);

  const handleScroll = useCallback(() => {
    const y = window.scrollY;
    setScrollY(y);
    setNavSolid(y > 60);
  }, []);

  useEffect(() => {
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, [handleScroll]);

  // The hero is what a fresh load shows, so it never waits on an observer:
  // it plays in as soon as the page is on screen.
  const [heroIn, setHeroIn] = useState(false);
  useEffect(() => {
    setHeroIn(true);
  }, []);
  const screenshotReveal = useRevealOnScroll<HTMLElement>(0.15);
  const invitedReveal = useRevealOnScroll<HTMLElement>(0.15);
  const toolsReveal = useRevealOnScroll<HTMLElement>(0.1);
  const galleryReveal = useRevealOnScroll<HTMLElement>(0.15);
  const principlesReveal = useRevealOnScroll<HTMLElement>(0.2);
  const docsReveal = useRevealOnScroll<HTMLElement>(0.15);
  const ctaReveal = useRevealOnScroll<HTMLElement>(0.2);

  const heroShot = screenshot("myTasks", isDark);
  const screenshots = useMemo(
    () => [
      {
        src: screenshot("myTasks", isDark),
        alt: t("gallery.tasksAlt"),
        caption: t("gallery.tasksCaption"),
      },
      {
        src: screenshot("project", isDark),
        alt: t("gallery.projectAlt"),
        caption: t("gallery.projectCaption"),
      },
      {
        src: screenshot("document", isDark),
        alt: t("gallery.documentAlt"),
        caption: t("gallery.documentCaption"),
      },
    ],
    [t, isDark]
  );

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <LogoIcon className="h-12 w-12 animate-pulse" />
          <p className="text-muted-foreground text-sm uppercase tracking-widest">
            {t("hero.loading")}
          </p>
        </div>
      </div>
    );
  }

  if (token) {
    return null;
  }

  const layerSlow = scrollY * 0.05;
  const layerMedium = scrollY * 0.12;
  const layerFast = scrollY * 0.2;

  const startButton = (size: "lg" | "default" = "lg", className = "") =>
    registrationOpen ? (
      <Button size={size} variant="outline" className={className} asChild>
        <Link to="/register">
          <Sparkles className="h-5 w-5" aria-hidden="true" />
          {t("hero.ctaStart")}
        </Link>
      </Button>
    ) : null;

  return (
    <div className="relative min-h-screen overflow-x-hidden bg-background">
      <style>{LANDING_KEYFRAMES}</style>

      {/* ================================================================== */}
      {/* Navigation */}
      {/* ================================================================== */}
      <nav
        className={`fixed top-0 right-0 left-0 z-50 transition-all duration-500 ${
          navSolid ? "bg-background/80 shadow-lg backdrop-blur-xl" : "bg-transparent"
        }`}
      >
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6 sm:py-4">
          <div className="flex items-center gap-2.5 font-bold text-primary text-xl tracking-tight">
            <LogoIcon className="h-8 w-8" aria-hidden="true" />
            <span className="pride-wordmark">initiative</span>
          </div>
          <div className="flex items-center gap-1 sm:gap-3">
            {catalog.data && (
              <Button
                variant="ghost"
                className="hidden text-foreground/80 hover:text-foreground sm:inline-flex"
                asChild
              >
                <a href="#pricing">{t("nav.pricing")}</a>
              </Button>
            )}
            <Button
              variant="ghost"
              className="hidden text-foreground/80 hover:text-foreground sm:inline-flex"
              asChild
            >
              <a href={DOCS_URL} target="_blank" rel="noopener noreferrer">
                {t("nav.help")}
              </a>
            </Button>
            <ModeToggle />
            <Button asChild>
              <Link to="/login" search={true}>
                {t("nav.signIn")}
              </Link>
            </Button>
          </div>
        </div>
      </nav>

      {/* ================================================================== */}
      {/* Hero */}
      {/* ================================================================== */}
      <section
        className="relative flex min-h-[100svh] flex-col items-center justify-center overflow-hidden pt-24 pb-16"
        aria-labelledby="landing-hero-title"
      >
        <div className="aurora-bg absolute inset-0" aria-hidden="true" />
        <div
          className="absolute inset-0 opacity-[0.2]"
          style={{
            backgroundImage: `url(${isDark ? "/images/hexWhite.svg" : "/images/hexBlack.svg"})`,
            backgroundSize: "37px 64px",
            backgroundPosition: "center",
            transform: `translateY(${layerSlow}px)`,
          }}
          aria-hidden="true"
        />
        <Starfield isDark={isDark} />

        <div
          className="absolute top-1/4 left-1/2 h-[500px] w-[500px] -translate-x-1/2 -translate-y-1/2 rounded-full md:h-[700px] md:w-[700px]"
          style={{
            background: isDark
              ? "radial-gradient(circle, rgba(100, 80, 240, 0.2) 0%, transparent 70%)"
              : "radial-gradient(circle, rgba(100, 80, 240, 0.08) 0%, transparent 70%)",
            animation: "heroGlow 6s ease-in-out infinite",
            transform: `translate(-50%, calc(-50% + ${layerSlow}px))`,
          }}
          aria-hidden="true"
        />
        <div
          className="absolute top-1/3 right-0 h-[300px] w-[300px] rounded-full md:h-[500px] md:w-[500px]"
          style={{
            background: isDark
              ? "radial-gradient(circle, rgba(200, 100, 255, 0.12) 0%, transparent 70%)"
              : "radial-gradient(circle, rgba(200, 100, 255, 0.05) 0%, transparent 70%)",
            animation: "heroGlow 8s ease-in-out 2s infinite",
            transform: `translateY(${layerMedium}px)`,
          }}
          aria-hidden="true"
        />

        <FloatingShape
          className="top-[15%] left-[8%]"
          parallaxOffset={-layerMedium}
          shape="hexagon"
          size={80}
          isDark={isDark}
        />
        <FloatingShape
          className="top-[25%] right-[12%]"
          parallaxOffset={-layerFast}
          shape="circle"
          size={60}
          isDark={isDark}
        />
        <FloatingShape
          className="bottom-[20%] left-[15%]"
          parallaxOffset={-layerSlow}
          shape="diamond"
          size={50}
          isDark={isDark}
        />
        <FloatingShape
          className="right-[8%] bottom-[30%]"
          parallaxOffset={-layerMedium}
          shape="ring"
          size={100}
          isDark={isDark}
        />
        <FloatingShape
          className="top-[10%] right-[30%]"
          parallaxOffset={-layerSlow}
          shape="ring"
          size={70}
          isDark={isDark}
        />

        <div
          className="relative z-10 mx-auto w-full max-w-5xl px-6 text-center"
          style={{ transform: `translateY(${layerSlow * 0.5}px)` }}
        >
          <div
            className={`mb-8 inline-flex items-center gap-2 rounded-full border px-5 py-2 font-medium text-sm transition-all duration-1000 ${reveal(heroIn)}`}
            style={{
              borderColor: isDark ? "rgba(140, 130, 255, 0.3)" : "rgba(100, 80, 200, 0.15)",
              background: isDark ? "rgba(140, 130, 255, 0.08)" : "rgba(100, 80, 200, 0.05)",
            }}
          >
            <Sparkles className="h-4 w-4 animate-pulse text-primary" aria-hidden="true" />
            <span className="text-primary">{t("hero.eyebrow")}</span>
          </div>

          <h1 id="landing-hero-title" className="mb-6" aria-label={t("hero.titleAria")}>
            <span
              className={`block font-black text-5xl text-foreground tracking-tight transition-all delay-300 duration-1000 sm:text-6xl md:text-7xl lg:text-8xl ${reveal(heroIn, "translate-y-12 opacity-0")}`}
            >
              {t("hero.titleLine1")}
            </span>
            <span className="relative mt-2 inline-block">
              <span
                className={`block font-black text-5xl text-primary tracking-tight transition-all delay-500 duration-1000 sm:text-6xl md:text-7xl lg:text-8xl ${reveal(heroIn, "translate-y-12 opacity-0")}`}
              >
                {t("hero.titleLine2")}
              </span>
              <span
                className="absolute bottom-0 left-0 h-1 rounded-full bg-primary/30 md:h-1.5"
                style={{
                  animation: heroIn ? "heroLine 1.2s ease-out 1s forwards" : "none",
                  width: 0,
                }}
                aria-hidden="true"
              />
            </span>
          </h1>

          <p
            className={`mx-auto max-w-2xl text-lg text-muted-foreground transition-all delay-700 duration-1000 md:text-xl ${reveal(heroIn)}`}
          >
            {t("hero.subtitle")}
          </p>

          <div
            className={`mt-10 flex flex-col items-stretch justify-center gap-3 transition-all delay-[900ms] duration-1000 sm:flex-row sm:items-center ${reveal(heroIn)}`}
          >
            <Button
              size="lg"
              className="h-12 px-8 font-semibold text-base transition-all duration-300 hover:scale-105 hover:shadow-lg hover:shadow-primary/25"
              asChild
            >
              <Link to="/login" search={true}>
                {t("hero.ctaSignIn")}
              </Link>
            </Button>
            {startButton(
              "lg",
              "h-12 px-8 font-semibold text-base transition-all duration-300 hover:scale-105"
            )}
          </div>
          <p
            className={`mt-5 text-muted-foreground text-sm transition-all delay-[1100ms] duration-1000 ${reveal(heroIn)}`}
          >
            {t("hero.invited")}
          </p>
        </div>

        {/* The ribbon: who this is for, scrolling past */}
        <div
          className={`landing-ribbon relative z-10 mt-14 w-full overflow-hidden transition-all delay-[1300ms] duration-1000 ${reveal(heroIn)}`}
          style={{
            maskImage: "linear-gradient(90deg, transparent, black 12%, black 88%, transparent)",
            WebkitMaskImage:
              "linear-gradient(90deg, transparent, black 12%, black 88%, transparent)",
          }}
        >
          <div
            className="landing-ribbon__track flex w-max gap-3 pr-3"
            style={{ animation: "ribbonScroll 40s linear infinite" }}
          >
            {[0, 1].map((copy) => (
              <ul
                key={copy}
                className="flex shrink-0 gap-3"
                aria-label={copy === 0 ? t("ribbon.aria") : undefined}
                aria-hidden={copy === 1 ? "true" : undefined}
              >
                {RIBBON_KEYS.map((key) => (
                  <li
                    key={key}
                    className="whitespace-nowrap rounded-full border px-4 py-1.5 font-medium text-foreground/80 text-sm"
                    style={surface(isDark)}
                  >
                    {t(`ribbon.${key}`)}
                  </li>
                ))}
              </ul>
            ))}
          </div>
        </div>

        <div
          className={`absolute bottom-6 left-1/2 hidden -translate-x-1/2 transition-all delay-[1800ms] duration-1000 md:block ${reveal(heroIn, "translate-y-4 opacity-0")}`}
        >
          <div className="flex flex-col items-center gap-2">
            <span className="text-muted-foreground/50 text-xs uppercase tracking-[0.2em]">
              {t("hero.scroll")}
            </span>
            <ChevronDown
              className="h-5 w-5 animate-bounce text-muted-foreground/50"
              aria-hidden="true"
            />
          </div>
        </div>
      </section>

      {/* ================================================================== */}
      {/* Hero screenshot */}
      {/* ================================================================== */}
      <section
        ref={screenshotReveal.ref}
        className="relative -mt-10 px-4 pb-12 sm:px-6 md:-mt-20 md:pb-20"
      >
        <div
          className={`relative z-20 mx-auto max-w-5xl transition-all duration-1000 ${
            screenshotReveal.isVisible
              ? "translate-y-0 scale-100 opacity-100"
              : "translate-y-12 scale-95 opacity-0"
          }`}
        >
          <ScreenshotFrame
            src={heroShot}
            alt={t("hero.screenshotAlt")}
            isDark={isDark}
            onClick={() => setLightbox({ src: heroShot, alt: t("hero.screenshotAlt") })}
          />
        </div>
      </section>

      {/* ================================================================== */}
      {/* Somebody added you */}
      {/* ================================================================== */}
      <section
        ref={invitedReveal.ref}
        className="relative overflow-hidden py-24 md:py-32"
        aria-labelledby="landing-invited-title"
      >
        <div className="relative z-10 mx-auto max-w-6xl px-6">
          <SectionHeading
            id="landing-invited-title"
            label={t("invited.sectionLabel")}
            title={t("invited.title")}
            description={t("invited.description")}
            visible={invitedReveal.isVisible}
          />
          <ol className="grid gap-4 md:grid-cols-3 md:gap-6">
            {INVITED_STEPS.map(({ icon: Icon, key }, i) => (
              <li
                key={key}
                className={`rounded-2xl border p-6 backdrop-blur-sm transition-all duration-700 ${reveal(invitedReveal.isVisible, "translate-y-10 opacity-0")}`}
                style={{ ...surface(isDark), transitionDelay: `${200 + i * 150}ms` }}
              >
                <div className="mb-4 flex items-center gap-3">
                  <div
                    className="flex h-11 w-11 items-center justify-center rounded-xl"
                    style={iconWell(isDark)}
                  >
                    <Icon className="h-5 w-5 text-primary" aria-hidden="true" />
                  </div>
                  <span className="font-black text-2xl text-primary/40">{i + 1}</span>
                </div>
                <h3 className="mb-2 font-bold text-foreground text-lg">
                  {t(`invited.${key}Title`)}
                </h3>
                <p className="text-muted-foreground leading-relaxed">{t(`invited.${key}Body`)}</p>
              </li>
            ))}
          </ol>
          <div
            className={`mt-10 text-center transition-all delay-[700ms] duration-700 ${reveal(invitedReveal.isVisible)}`}
          >
            <Button variant="link" className="text-base" asChild>
              <a
                href={docsUrl("getting-started/a-quick-tour/")}
                target="_blank"
                rel="noopener noreferrer"
              >
                {t("invited.cta")}
                <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
              </a>
            </Button>
          </div>
        </div>
      </section>

      {/* ================================================================== */}
      {/* Tools — the registry, one card each */}
      {/* ================================================================== */}
      <section
        ref={toolsReveal.ref}
        className="relative overflow-hidden py-24 md:py-32"
        aria-labelledby="landing-tools-title"
      >
        <div
          className="absolute inset-0 opacity-[0.02]"
          style={{
            backgroundImage: `url(${isDark ? "/images/hexWhite.svg" : "/images/hexBlack.svg"})`,
            backgroundSize: "28px 48px",
          }}
          aria-hidden="true"
        />
        <Starfield isDark={isDark} />
        <div className="relative z-10 mx-auto max-w-6xl px-6">
          <SectionHeading
            id="landing-tools-title"
            label={t("tools.sectionLabel")}
            title={t("tools.title")}
            description={t("tools.description")}
            visible={toolsReveal.isVisible}
          />
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {TOOLS.map((tool, i) => {
              const Icon = TOOL_ICONS[tool];
              return (
                <li
                  key={tool}
                  className={`group rounded-2xl border p-6 transition-all duration-700 hover:-translate-y-1 hover:shadow-lg ${reveal(toolsReveal.isVisible, "translate-y-10 opacity-0")}`}
                  style={{ ...surface(isDark), transitionDelay: `${100 + i * 80}ms` }}
                  data-tool={tool}
                >
                  <div className="mb-4 flex items-center gap-3">
                    <div
                      className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl transition-transform duration-300 group-hover:rotate-6"
                      style={iconWell(isDark)}
                    >
                      <Icon className="h-5 w-5 text-primary" aria-hidden="true" />
                    </div>
                    <h3 className="font-bold text-foreground text-lg">
                      {tNav(toolNavLabelKey(tool))}
                    </h3>
                  </div>
                  {/* The same sketch the create wizard draws, so a tool looks
                      here like it will when they meet it inside. */}
                  <div className="mb-4">
                    <ToolSketch tool={tool} active />
                  </div>
                  <p className="text-muted-foreground text-sm leading-relaxed">
                    {t(`tools.${toolCamelPlural(tool)}` as ParseKeys<"landing">)}
                  </p>
                </li>
              );
            })}
          </ul>
        </div>
      </section>

      {/* ================================================================== */}
      {/* Gallery */}
      {/* ================================================================== */}
      <section
        ref={galleryReveal.ref}
        className="relative overflow-hidden py-24 md:py-32"
        aria-labelledby="landing-gallery-title"
      >
        <div
          className="absolute inset-0"
          style={{
            background: isDark
              ? "linear-gradient(180deg, transparent 0%, rgba(100, 80, 240, 0.04) 50%, transparent 100%)"
              : "linear-gradient(180deg, transparent 0%, rgba(100, 80, 200, 0.02) 50%, transparent 100%)",
          }}
          aria-hidden="true"
        />
        <div className="relative z-10 mx-auto max-w-6xl px-6">
          <SectionHeading
            id="landing-gallery-title"
            label={t("gallery.sectionLabel")}
            title={t("gallery.title")}
            visible={galleryReveal.isVisible}
          />
          <div className="grid gap-8 md:grid-cols-3 md:gap-6">
            {screenshots.map((shot, i) => (
              <figure
                key={shot.src}
                className={`landing-float transition-all duration-700 ${reveal(galleryReveal.isVisible, "translate-y-10 opacity-0")}`}
                style={
                  {
                    transitionDelay: `${200 + i * 200}ms`,
                    "--tilt": `${SCREENSHOT_TILTS[i]}deg`,
                    animation: galleryReveal.isVisible
                      ? `cardFloat ${7 + i}s ease-in-out ${i * 0.8}s infinite`
                      : "none",
                  } as React.CSSProperties
                }
              >
                <ScreenshotFrame
                  src={shot.src}
                  alt={shot.alt}
                  isDark={isDark}
                  onClick={() => setLightbox({ src: shot.src, alt: shot.alt })}
                />
                <figcaption className="mt-3 text-center text-muted-foreground text-sm">
                  {shot.caption}
                </figcaption>
              </figure>
            ))}
          </div>
        </div>
      </section>

      {/* ================================================================== */}
      {/* Plans — only where there is a portal to describe them */}
      {/* ================================================================== */}
      {billing && !catalog.isError && (
        <PricingSection
          portalUrl={billing.url}
          catalog={catalog.data}
          isDark={isDark}
          registrationOpen={registrationOpen}
        />
      )}

      {/* ================================================================== */}
      {/* What stays true either way */}
      {/* ================================================================== */}
      <section
        ref={principlesReveal.ref}
        className="relative overflow-hidden py-20 md:py-24"
        aria-label={t("principles.openSourceTitle")}
      >
        <div className="relative z-10 mx-auto max-w-6xl px-6">
          <ul className="grid grid-cols-2 gap-6 md:grid-cols-4 md:gap-10">
            {PRINCIPLES.map(({ icon: Icon, key }, i) => (
              <li
                key={key}
                className={`flex flex-col items-center gap-3 text-center transition-all duration-700 ${reveal(principlesReveal.isVisible, "translate-y-10 opacity-0")}`}
                style={{ transitionDelay: `${i * 150}ms` }}
              >
                <div
                  className="flex h-14 w-14 items-center justify-center rounded-2xl"
                  style={iconWell(isDark)}
                >
                  <Icon className="h-6 w-6 text-primary" aria-hidden="true" />
                </div>
                <span className="font-bold text-foreground text-lg">
                  {t(`principles.${key}Title`)}
                </span>
                <span className="text-muted-foreground text-sm">{t(`principles.${key}Body`)}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ================================================================== */}
      {/* Get the app */}
      {/* ================================================================== */}
      <DownloadSection minNativeVersion={config?.min_native_version ?? null} isDark={isDark} />

      {/* ================================================================== */}
      {/* Help center */}
      {/* ================================================================== */}
      <section
        ref={docsReveal.ref}
        className="relative overflow-hidden py-24 md:py-32"
        aria-labelledby="landing-docs-title"
      >
        <div
          className="absolute inset-0"
          style={{
            background: isDark
              ? "linear-gradient(180deg, transparent 0%, rgba(100, 80, 240, 0.04) 50%, transparent 100%)"
              : "linear-gradient(180deg, transparent 0%, rgba(100, 80, 200, 0.02) 50%, transparent 100%)",
          }}
          aria-hidden="true"
        />
        <div className="relative z-10 mx-auto max-w-6xl px-6">
          <SectionHeading
            id="landing-docs-title"
            label={t("docs.sectionLabel")}
            title={t("docs.title")}
            description={t("docs.description")}
            visible={docsReveal.isVisible}
          />
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {DOC_LINKS.map(({ icon: Icon, key, path }, i) => (
              <li
                key={key}
                className={`transition-all duration-700 ${reveal(docsReveal.isVisible, "translate-y-10 opacity-0")}`}
                style={{ transitionDelay: `${100 + i * 80}ms` }}
              >
                <a
                  href={docsUrl(path)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex h-full items-start gap-4 rounded-2xl border p-5 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-lg"
                  style={surface(isDark)}
                >
                  <div
                    className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl"
                    style={iconWell(isDark)}
                  >
                    <Icon className="h-5 w-5 text-primary" aria-hidden="true" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <h3 className="flex items-center gap-1 font-bold text-foreground">
                      {t(`docs.${key}Title`)}
                      <ArrowUpRight
                        className="h-4 w-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
                        aria-hidden="true"
                      />
                    </h3>
                    <p className="mt-1 text-muted-foreground text-sm">{t(`docs.${key}Body`)}</p>
                  </div>
                </a>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ================================================================== */}
      {/* Final call */}
      {/* ================================================================== */}
      <section
        ref={ctaReveal.ref}
        className="relative overflow-hidden py-28 md:py-40"
        aria-labelledby="landing-cta-title"
      >
        <div
          className="absolute inset-0"
          style={{
            background: isDark
              ? "radial-gradient(ellipse 80% 50% at 50% 50%, rgba(100, 80, 240, 0.1) 0%, transparent 70%)"
              : "radial-gradient(ellipse 80% 50% at 50% 50%, rgba(100, 80, 200, 0.05) 0%, transparent 70%)",
          }}
          aria-hidden="true"
        />
        <FloatingShape
          className="top-[20%] left-[10%]"
          parallaxOffset={0}
          shape="hexagon"
          size={60}
          isDark={isDark}
        />
        <FloatingShape
          className="right-[10%] bottom-[20%]"
          parallaxOffset={0}
          shape="ring"
          size={80}
          isDark={isDark}
        />
        <div className="relative z-10 mx-auto max-w-3xl px-6 text-center">
          <div
            className={`transition-all duration-1000 ${
              ctaReveal.isVisible
                ? "translate-y-0 scale-100 opacity-100"
                : "translate-y-10 scale-95 opacity-0"
            }`}
          >
            <h2
              id="landing-cta-title"
              className="mb-6 font-bold text-4xl text-foreground tracking-tight md:text-6xl"
            >
              {t("cta.title")}
            </h2>
            <p className="mx-auto mb-10 max-w-xl text-lg text-muted-foreground md:text-xl">
              {t("cta.description")}
            </p>
            <div className="flex flex-col items-stretch justify-center gap-3 sm:flex-row sm:items-center">
              <Button
                size="lg"
                className="h-14 px-10 font-semibold text-lg transition-all duration-300 hover:scale-105 hover:shadow-primary/25 hover:shadow-xl"
                asChild
              >
                <Link to="/login" search={true}>
                  {t("cta.signIn")}
                </Link>
              </Button>
              {startButton("lg", "h-14 px-10 font-semibold text-lg")}
            </div>
          </div>
        </div>
      </section>

      {/* ================================================================== */}
      {/* Footer */}
      {/* ================================================================== */}
      <footer
        className="relative border-t"
        style={{ borderColor: isDark ? "rgba(140, 130, 255, 0.1)" : "rgba(100, 80, 200, 0.06)" }}
      >
        <div className="mx-auto max-w-7xl px-6 py-10">
          <div className="flex flex-col items-center justify-between gap-6 md:flex-row">
            <div className="flex items-center gap-2 font-semibold text-primary">
              <LogoIcon className="h-6 w-6" aria-hidden="true" />
              <span className="pride-wordmark">initiative</span>
            </div>
            <nav className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm">
              <a
                href={DOCS_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-muted-foreground hover:text-foreground"
              >
                <LifeBuoy className="h-4 w-4" aria-hidden="true" />
                {t("footer.docs")}
              </a>
              <a
                href={REPO_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-muted-foreground hover:text-foreground"
              >
                <Code2 className="h-4 w-4" aria-hidden="true" />
                {t("footer.source")}
              </a>
              <a
                href={CHANGELOG_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-muted-foreground hover:text-foreground"
              >
                <Sparkles className="h-4 w-4" aria-hidden="true" />
                {t("footer.changelog")}
              </a>
            </nav>
            <p className="text-muted-foreground text-sm">
              {t("footer.copyright", { year: new Date().getFullYear() })}
            </p>
          </div>
        </div>
      </footer>

      {lightbox && (
        <ScreenshotLightbox
          src={lightbox.src}
          alt={lightbox.alt}
          isDark={isDark}
          onClose={() => setLightbox(null)}
        />
      )}
    </div>
  );
};
