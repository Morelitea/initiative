import i18n from "i18next";
import type { LanguageDetectorModule } from "i18next";
import { initReactI18next } from "react-i18next";
import HttpBackend from "i18next-http-backend";

import { getItem, setItem } from "@/lib/storage";

export const defaultNS = "common";
export const namespaces = [
  "common",
  "auth",
  "nav",
  "projects",
  "tasks",
  "documents",
  "initiatives",
  "settings",
  "tags",
  "guilds",
  "import",
  "notifications",
  "stats",
  "landing",
  "errors",
  "dates",
  "dashboard",
] as const;

const LANGUAGE_STORAGE_KEY = "initiative-language";

/**
 * Custom language detector that uses the app's storage abstraction
 * instead of accessing localStorage directly. This ensures language
 * preference persists correctly on native platforms via Capacitor
 * Preferences.
 */
const storageLanguageDetector: LanguageDetectorModule = {
  type: "languageDetector",
  init() {},
  detect() {
    const stored = getItem(LANGUAGE_STORAGE_KEY);
    if (stored) {
      return stored;
    }
    // Fall back to browser language
    if (typeof navigator !== "undefined") {
      return navigator.language;
    }
    return undefined;
  },
  cacheUserLanguage(lng: string) {
    setItem(LANGUAGE_STORAGE_KEY, lng);
  },
};

void i18n
  .use(HttpBackend)
  .use(storageLanguageDetector)
  .use(initReactI18next)
  .init({
    load: "languageOnly",
    fallbackLng: "en",
    defaultNS,
    fallbackNS: "common",
    ns: ["common"],
    partialBundledLanguages: true,
    interpolation: {
      escapeValue: false,
    },
    backend: {
      loadPath: "/locales/{{lng}}/{{ns}}.json",
      queryStringParams: { v: __APP_VERSION__ },
    },
    react: {
      useSuspense: true,
    },
  });

export default i18n;
