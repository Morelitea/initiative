import { describe, expect, it, vi } from "vitest";

/** Preferences as the native plugin keeps it: one store per group, and a
 *  current group set by `configure`. */
const groups = vi.hoisted(() => {
  const stores = new Map<string, Map<string, string>>();
  let current = "CapacitorStorage";
  const store = () => {
    if (!stores.has(current)) stores.set(current, new Map());
    return stores.get(current) as Map<string, string>;
  };
  return {
    stores,
    Preferences: {
      configure: async ({ group }: { group: string }) => {
        current = group;
      },
      keys: async () => ({ keys: [...store().keys()] }),
      get: async ({ key }: { key: string }) => ({ value: store().get(key) ?? null }),
      set: async ({ key, value }: { key: string; value: string }) => {
        store().set(key, value);
      },
      remove: async ({ key }: { key: string }) => {
        store().delete(key);
      },
    },
  };
});

vi.mock("@capacitor/core", () => ({ Capacitor: { isNativePlatform: () => true } }));
vi.mock("@capacitor/preferences", () => ({ Preferences: groups.Preferences }));

import { CREDENTIAL_KEYS, getItem, initStorage, setItem } from "./storage";

describe("native storage", () => {
  it("keeps credentials in their own group, and moves ones kept before it", async () => {
    groups.stores.set(
      "CapacitorStorage",
      new Map([
        ["initiative-server-url", "http://192.168.1.20:8173/api/v1"],
        [CREDENTIAL_KEYS.token, "device-token"],
      ])
    );

    await initStorage();
    await setItem(CREDENTIAL_KEYS.refreshToken, "rt-1");
    await setItem("initiative-theme", "dark");

    expect(getItem(CREDENTIAL_KEYS.token)).toBe("device-token");
    expect(Object.fromEntries(groups.stores.get("CapacitorStorage") ?? [])).toEqual({
      "initiative-server-url": "http://192.168.1.20:8173/api/v1",
      "initiative-theme": "dark",
    });
    expect(Object.fromEntries(groups.stores.get("InitiativeCredentials") ?? [])).toEqual({
      [CREDENTIAL_KEYS.token]: "device-token",
      [CREDENTIAL_KEYS.refreshToken]: "rt-1",
    });
  });
});
