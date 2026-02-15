import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const FRONTEND_LOCALES_DIR = path.resolve(__dirname, "../../public/locales");
const BACKEND_LOCALES_DIR = path.resolve(__dirname, "../../../backend/app/locales");
const SOURCE_LOCALE = "en";

/**
 * Recursively collect all leaf key paths from a nested JSON object.
 * e.g. { a: { b: "x", c: "y" } } → ["a.b", "a.c"]
 */
const collectKeys = (obj: Record<string, unknown>, prefix = ""): string[] => {
  const keys: string[] = [];
  for (const [key, value] of Object.entries(obj)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    if (value !== null && typeof value === "object" && !Array.isArray(value)) {
      keys.push(...collectKeys(value as Record<string, unknown>, fullKey));
    } else {
      keys.push(fullKey);
    }
  }
  return keys.sort();
};

const loadJson = (filePath: string): Record<string, unknown> =>
  JSON.parse(fs.readFileSync(filePath, "utf-8"));

const getLocales = (localesDir: string): string[] =>
  fs
    .readdirSync(localesDir, { withFileTypes: true })
    .filter((d) => d.isDirectory() && d.name !== SOURCE_LOCALE && d.name !== "pseudo")
    .map((d) => d.name);

const getNamespaces = (localesDir: string, locale: string): string[] =>
  fs
    .readdirSync(path.join(localesDir, locale))
    .filter((f) => f.endsWith(".json"))
    .map((f) => f.replace(".json", ""));

// --- Frontend locale tests ---

describe("Frontend locale key parity", () => {
  const locales = getLocales(FRONTEND_LOCALES_DIR);
  const sourceNamespaces = getNamespaces(FRONTEND_LOCALES_DIR, SOURCE_LOCALE);

  for (const locale of locales) {
    describe(`${locale} vs ${SOURCE_LOCALE}`, () => {
      it("should have the same namespace files", () => {
        const targetNamespaces = getNamespaces(FRONTEND_LOCALES_DIR, locale);
        const missingInTarget = sourceNamespaces.filter((ns) => !targetNamespaces.includes(ns));
        const extraInTarget = targetNamespaces.filter((ns) => !sourceNamespaces.includes(ns));
        expect(missingInTarget, `Missing namespace files in ${locale}`).toEqual([]);
        expect(extraInTarget, `Extra namespace files in ${locale}`).toEqual([]);
      });

      for (const namespace of sourceNamespaces) {
        describe(`${namespace}.json`, () => {
          const sourcePath = path.join(FRONTEND_LOCALES_DIR, SOURCE_LOCALE, `${namespace}.json`);
          const targetPath = path.join(FRONTEND_LOCALES_DIR, locale, `${namespace}.json`);

          it("should exist", () => {
            expect(fs.existsSync(targetPath), `${locale}/${namespace}.json is missing`).toBe(true);
          });

          it("should have no missing keys", () => {
            if (!fs.existsSync(targetPath)) return;
            const sourceKeys = collectKeys(loadJson(sourcePath));
            const targetKeys = collectKeys(loadJson(targetPath));
            const missing = sourceKeys.filter((k) => !targetKeys.includes(k));
            expect(missing, `Keys in ${SOURCE_LOCALE} but missing in ${locale}`).toEqual([]);
          });

          it("should have no extra keys", () => {
            if (!fs.existsSync(targetPath)) return;
            const sourceKeys = collectKeys(loadJson(sourcePath));
            const targetKeys = collectKeys(loadJson(targetPath));
            const extra = targetKeys.filter((k) => !sourceKeys.includes(k));
            expect(extra, `Keys in ${locale} but not in ${SOURCE_LOCALE}`).toEqual([]);
          });

          it("should preserve interpolation placeholders", () => {
            if (!fs.existsSync(targetPath)) return;
            const sourceData = loadJson(sourcePath);
            const targetData = loadJson(targetPath);
            const sourceKeys = collectKeys(sourceData);
            const errors: string[] = [];

            for (const key of sourceKeys) {
              const sourceVal = getNestedValue(sourceData, key);
              const targetVal = getNestedValue(targetData, key);
              if (typeof sourceVal !== "string" || typeof targetVal !== "string") continue;

              // Check {{variable}} placeholders
              const sourcePlaceholders = (sourceVal.match(/\{\{[^}]+\}\}/g) ?? []).sort();
              const targetPlaceholders = (targetVal.match(/\{\{[^}]+\}\}/g) ?? []).sort();
              if (JSON.stringify(sourcePlaceholders) !== JSON.stringify(targetPlaceholders)) {
                errors.push(
                  `${key}: expected {{placeholders}} ${JSON.stringify(sourcePlaceholders)}, got ${JSON.stringify(targetPlaceholders)}`
                );
              }
            }
            expect(errors, "Mismatched interpolation placeholders").toEqual([]);
          });
        });
      }
    });
  }
});

// --- Backend locale tests ---

if (fs.existsSync(BACKEND_LOCALES_DIR)) {
  describe("Backend locale key parity", () => {
    const locales = getLocales(BACKEND_LOCALES_DIR);
    const sourceNamespaces = getNamespaces(BACKEND_LOCALES_DIR, SOURCE_LOCALE);

    for (const locale of locales) {
      describe(`${locale} vs ${SOURCE_LOCALE}`, () => {
        for (const namespace of sourceNamespaces) {
          describe(`${namespace}.json`, () => {
            const sourcePath = path.join(BACKEND_LOCALES_DIR, SOURCE_LOCALE, `${namespace}.json`);
            const targetPath = path.join(BACKEND_LOCALES_DIR, locale, `${namespace}.json`);

            it("should exist", () => {
              expect(fs.existsSync(targetPath), `${locale}/${namespace}.json is missing`).toBe(
                true
              );
            });

            it("should have no missing keys", () => {
              if (!fs.existsSync(targetPath)) return;
              const sourceKeys = collectKeys(loadJson(sourcePath));
              const targetKeys = collectKeys(loadJson(targetPath));
              const missing = sourceKeys.filter((k) => !targetKeys.includes(k));
              expect(missing, `Keys in ${SOURCE_LOCALE} but missing in ${locale}`).toEqual([]);
            });

            it("should have no extra keys", () => {
              if (!fs.existsSync(targetPath)) return;
              const sourceKeys = collectKeys(loadJson(sourcePath));
              const targetKeys = collectKeys(loadJson(targetPath));
              const extra = targetKeys.filter((k) => !sourceKeys.includes(k));
              expect(extra, `Keys in ${locale} but not in ${SOURCE_LOCALE}`).toEqual([]);
            });
          });
        }
      });
    }
  });
}

// --- Helper ---

const getNestedValue = (obj: Record<string, unknown>, keyPath: string): unknown => {
  const parts = keyPath.split(".");
  let current: unknown = obj;
  for (const part of parts) {
    if (current === null || typeof current !== "object") return undefined;
    current = (current as Record<string, unknown>)[part];
  }
  return current;
};
