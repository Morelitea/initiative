import fs from "node:fs";
import path from "node:path";

import i18n from "i18next";
import { initReactI18next } from "react-i18next";

/**
 * Minimal synchronous i18n initialization for tests.
 *
 * The app's production i18n setup uses HTTP backend + Suspense, which
 * doesn't play well with component tests. Instead we pre-load every
 * English namespace from disk so `useTranslation()` resolves keys
 * immediately without touching the network.
 */
const LOCALES_DIR = path.resolve(__dirname, "../../../public/locales/en");

const loadResources = (): Record<string, Record<string, unknown>> => {
  const resources: Record<string, Record<string, unknown>> = {};
  if (!fs.existsSync(LOCALES_DIR)) return resources;

  for (const file of fs.readdirSync(LOCALES_DIR)) {
    if (!file.endsWith(".json")) continue;
    const ns = file.replace(/\.json$/, "");
    const full = path.join(LOCALES_DIR, file);
    try {
      resources[ns] = JSON.parse(fs.readFileSync(full, "utf-8")) as Record<string, unknown>;
    } catch {
      // ignore bad JSON — the locale-keys test catches those separately
    }
  }
  return resources;
};

if (!i18n.isInitialized) {
  void i18n.use(initReactI18next).init({
    lng: "en",
    fallbackLng: "en",
    defaultNS: "common",
    fallbackNS: "common",
    ns: [],
    interpolation: { escapeValue: false },
    resources: { en: loadResources() },
    react: { useSuspense: false },
  });
}

export default i18n;
