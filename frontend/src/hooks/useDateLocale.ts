import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { enUS, es } from "date-fns/locale";
import type { Locale } from "date-fns";

const LOCALE_MAP: Record<string, Locale> = {
  en: enUS,
  es: es,
};

/**
 * Returns the date-fns Locale matching the current i18n language.
 * Falls back to `enUS` for unknown languages.
 */
export const useDateLocale = (): Locale => {
  const { i18n } = useTranslation();
  return useMemo(() => LOCALE_MAP[i18n.language] ?? enUS, [i18n.language]);
};
