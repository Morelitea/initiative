/**
 * Widget metadata: how a name is read for a language, and the built-ins naming
 * themselves in every language the app ships.
 */
import { describe, expect, it } from "vitest";

import { BUILTIN_WIDGET_TYPES, builtinWidget } from "./registry";
import { localized, widgetDisplayName } from "./widgetMeta";

const SHIPPED_LOCALES = ["de", "en", "es", "fr"];

describe("localized", () => {
  const text = { en: "Chart", de: "Diagramm", "pt-BR": "Gráfico" };

  it("prefers an exact tag, then the base language", () => {
    expect(localized(text, "de")).toBe("Diagramm");
    expect(localized(text, "de-AT")).toBe("Diagramm");
    expect(localized(text, "pt-BR")).toBe("Gráfico");
  });

  it("falls back to English, then to whatever was supplied", () => {
    expect(localized(text, "ja")).toBe("Chart");
    expect(localized({ de: "Nur Deutsch" }, "ja")).toBe("Nur Deutsch");
    expect(localized(undefined, "en")).toBeUndefined();
  });

  it("falls back to the type id when a widget ships no name", () => {
    expect(widgetDisplayName(null, "gantt", "en")).toBe("gantt");
  });
});

describe("the built-ins name themselves", () => {
  it.each(BUILTIN_WIDGET_TYPES)("%s names and describes itself", (type) => {
    const meta = builtinWidget(type)?.meta;

    // Every language the app ships, so no viewer sees a raw type id.
    for (const locale of SHIPPED_LOCALES) {
      expect(meta?.name[locale], `${type} has no ${locale} name`).toBeTruthy();
      expect(meta?.description?.[locale], `${type} has no ${locale} description`).toBeTruthy();
    }
  });

  it.each(BUILTIN_WIDGET_TYPES)("%s labels each of its own options", (type) => {
    const meta = builtinWidget(type)?.meta;

    for (const [key, option] of Object.entries(meta?.options ?? {})) {
      for (const locale of SHIPPED_LOCALES) {
        expect(option.label[locale], `${type}.${key} has no ${locale} label`).toBeTruthy();
      }
      for (const [value, label] of Object.entries(option.values ?? {})) {
        for (const locale of SHIPPED_LOCALES) {
          expect(label[locale], `${type}.${key}=${value} has no ${locale} label`).toBeTruthy();
        }
      }
    }
  });
});
