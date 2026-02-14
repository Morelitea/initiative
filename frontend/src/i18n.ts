import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import HttpBackend from "i18next-http-backend";
import LanguageDetector from "i18next-browser-languagedetector";

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
] as const;

void i18n
  .use(HttpBackend)
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    fallbackLng: "en",
    defaultNS,
    ns: ["common"],
    partialBundledLanguages: true,
    interpolation: {
      escapeValue: false,
    },
    backend: {
      loadPath: "/locales/{{lng}}/{{ns}}.json",
    },
    detection: {
      order: ["localStorage", "navigator"],
      caches: ["localStorage"],
      lookupLocalStorage: "initiative-language",
    },
    react: {
      useSuspense: true,
    },
  });

export default i18n;
