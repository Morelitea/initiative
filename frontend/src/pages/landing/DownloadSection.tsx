/**
 * Getting the app onto a device, with the visitor's own device first.
 *
 * Android gets a real file: the APK attached to the release the server's
 * native floor names, which is the newest one that runs this server's web
 * bundle. Everything else installs from the browser, so those cards point at
 * the step in the install guide.
 */

import type { LucideIcon } from "lucide-react";
import { ArrowUpRight, Download, Monitor, Smartphone, TabletSmartphone } from "lucide-react";
import { useMemo } from "react";
import { Trans, useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { androidApkUrl, docsUrl, OBTAINIUM_URL, RELEASES_URL } from "@/lib/links";

import { reveal, useRevealOnScroll } from "./effects";
import { detectPlatform, type VisitorPlatform } from "./platform";

const INSTALL_GUIDE = docsUrl("getting-started/install-the-app/");
const BROWSER_INSTALL = `${INSTALL_GUIDE}#install-it-from-the-browser`;
const ANDROID_INSTALL = `${INSTALL_GUIDE}#the-android-app`;

interface DownloadSectionProps {
  /** The release whose APK this server's bundle runs on; null until the
   *  config has loaded, when the button falls back to the release listing. */
  minNativeVersion: string | null;
  isDark: boolean;
}

const PLATFORM_ORDER: VisitorPlatform[] = ["android", "ios", "desktop"];

const PLATFORM_ICON: Record<VisitorPlatform, LucideIcon> = {
  android: Smartphone,
  ios: TabletSmartphone,
  desktop: Monitor,
};

const PLATFORM_NAME_KEY = {
  android: "download.platformAndroid",
  ios: "download.platformIos",
  desktop: "download.platformDesktop",
} as const;

const PlatformCard = ({
  platform,
  detected,
  minNativeVersion,
  isDark,
  visible,
  index,
}: {
  platform: VisitorPlatform;
  detected: boolean;
  minNativeVersion: string | null;
  isDark: boolean;
  visible: boolean;
  index: number;
}) => {
  const { t } = useTranslation("landing");
  const Icon = PLATFORM_ICON[platform];

  const body = (() => {
    switch (platform) {
      case "android":
        return (
          <>
            <Button size="lg" className="w-full" variant={detected ? "default" : "outline"} asChild>
              {minNativeVersion ? (
                <a href={androidApkUrl(minNativeVersion)} download data-testid="android-apk">
                  <Download className="h-5 w-5" aria-hidden="true" />
                  {t("download.androidButton")}
                </a>
              ) : (
                <a href={RELEASES_URL} target="_blank" rel="noopener noreferrer">
                  <Download className="h-5 w-5" aria-hidden="true" />
                  {t("download.androidReleases")}
                </a>
              )}
            </Button>
            <p className="text-muted-foreground text-sm">
              <Trans
                t={t}
                i18nKey="download.androidNote"
                components={{
                  1: (
                    // biome-ignore lint/a11y/useAnchorContent: Trans fills the link with the translated text
                    <a
                      href={OBTAINIUM_URL}
                      className="font-medium text-primary underline-offset-4 hover:underline"
                    />
                  ),
                }}
              />
            </p>
          </>
        );
      case "ios":
        return (
          <>
            <Button size="lg" className="w-full" variant={detected ? "default" : "outline"} asChild>
              <a href={BROWSER_INSTALL} target="_blank" rel="noopener noreferrer">
                {t("download.iosButton")}
                <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
              </a>
            </Button>
            <p className="text-muted-foreground text-sm">{t("download.iosNote")}</p>
          </>
        );
      case "desktop":
        return (
          <>
            <Button size="lg" className="w-full" variant={detected ? "default" : "outline"} asChild>
              <a href={BROWSER_INSTALL} target="_blank" rel="noopener noreferrer">
                {t("download.desktopButton")}
                <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
              </a>
            </Button>
            <p className="text-muted-foreground text-sm">{t("download.desktopNote")}</p>
          </>
        );
    }
  })();

  return (
    <li
      className={`flex flex-col gap-4 rounded-2xl border p-6 transition-all duration-700 ${
        detected ? "shadow-lg shadow-primary/15 ring-1 ring-primary/40" : ""
      } ${reveal(visible, "translate-y-10 opacity-0")}`}
      style={{
        transitionDelay: `${index * 120}ms`,
        background: isDark ? "rgba(30, 25, 60, 0.45)" : "rgba(255, 255, 255, 0.7)",
        borderColor: isDark ? "rgba(140, 130, 255, 0.14)" : "rgba(100, 80, 200, 0.1)",
      }}
      data-platform={platform}
      data-detected={detected || undefined}
    >
      <div className="flex items-center gap-3">
        <div
          className="flex h-11 w-11 items-center justify-center rounded-xl"
          style={{
            background: isDark ? "rgba(140, 130, 255, 0.1)" : "rgba(100, 80, 200, 0.06)",
          }}
        >
          <Icon className="h-5 w-5 text-primary" aria-hidden="true" />
        </div>
        <div>
          <h3 className="font-bold text-foreground text-lg">{t(`download.${platform}Title`)}</h3>
          {detected && (
            <p className="text-primary text-xs">
              {t("download.detected", { platform: t(PLATFORM_NAME_KEY[platform]) })}
            </p>
          )}
        </div>
      </div>
      {body}
    </li>
  );
};

export const DownloadSection = ({ minNativeVersion, isDark }: DownloadSectionProps) => {
  const { t } = useTranslation("landing");
  const { ref, isVisible } = useRevealOnScroll<HTMLElement>(0.1);
  const detected = useMemo(() => detectPlatform(), []);
  // The visitor's own device leads; the rest follow in a fixed order so the
  // page reads the same for two people on the same phone.
  const ordered = [detected, ...PLATFORM_ORDER.filter((p) => p !== detected)];

  return (
    <section
      ref={ref}
      id="download"
      className="relative overflow-hidden py-24 md:py-32"
      aria-labelledby="landing-download-title"
    >
      <div className="relative z-10 mx-auto max-w-6xl px-6">
        <div className={`mb-12 text-center transition-all duration-1000 ${reveal(isVisible)}`}>
          <span className="mb-4 block font-semibold text-primary text-sm uppercase tracking-[0.2em]">
            {t("download.sectionLabel")}
          </span>
          <h2
            id="landing-download-title"
            className="mb-4 font-bold text-3xl text-foreground tracking-tight md:text-5xl"
          >
            {t("download.title")}
          </h2>
          <p className="mx-auto max-w-2xl text-lg text-muted-foreground">
            {t("download.description")}
          </p>
        </div>

        <ul className="grid gap-4 md:grid-cols-3 md:gap-6">
          {ordered.map((platform, i) => (
            <PlatformCard
              key={platform}
              platform={platform}
              detected={platform === detected}
              minNativeVersion={minNativeVersion}
              isDark={isDark}
              visible={isVisible}
              index={i}
            />
          ))}
        </ul>

        <div className="mt-8 text-center">
          <Button variant="link" asChild>
            <a href={ANDROID_INSTALL} target="_blank" rel="noopener noreferrer">
              {t("download.guide")}
              <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
            </a>
          </Button>
        </div>
      </div>
    </section>
  );
};
