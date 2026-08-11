/**
 * Every widget failure has a message, in every language we ship.
 *
 * The error tile is the only thing a viewer sees when a widget goes wrong, so
 * an unlocalized code there is a raw machine string on someone's dashboard.
 * Adding a failure mode without a translation fails here instead.
 */
import { describe, expect, it } from "vitest";

import { WIDGET_ERROR_CODES } from "./errors";

const localeModules = import.meta.glob<Record<string, unknown>>(
  "../../../public/locales/*/dashboards.json",
  { eager: true, import: "default" }
);

const locales = Object.entries(localeModules).map(([path, messages]) => ({
  locale: path.split("/").at(-2) as string,
  widgetError: (messages.widgetError ?? {}) as Record<string, string>,
}));

describe("widget error messages", () => {
  it("ships every locale the app has", () => {
    expect(locales.map((entry) => entry.locale).sort()).toEqual(["de", "en", "es", "fr"]);
  });

  it.each(locales)("$locale covers every error code", ({ widgetError }) => {
    for (const code of WIDGET_ERROR_CODES) {
      expect(widgetError[code], `missing message for ${code}`).toBeTruthy();
    }
    expect(widgetError.default, "missing fallback message").toBeTruthy();
  });

  it.each(locales)("$locale has no message for a code we removed", ({ widgetError }) => {
    const known = new Set<string>([...WIDGET_ERROR_CODES, "default"]);
    for (const key of Object.keys(widgetError)) {
      expect(known.has(key), `stale message for ${key}`).toBe(true);
    }
  });

  it.each(locales)(
    "$locale is actually translated, not copied from en",
    ({ locale, widgetError }) => {
      if (locale === "en") return;
      const english = locales.find((entry) => entry.locale === "en")?.widgetError ?? {};
      const identical = Object.keys(widgetError).filter((key) => widgetError[key] === english[key]);
      expect(identical, `${locale} left untranslated: ${identical.join(", ")}`).toHaveLength(0);
    }
  );
});
