import { Capacitor } from "@capacitor/core";
import { vi } from "vitest";

/**
 * Runs the test as a phone app whose store does not allow a link to a web
 * purchase: the iPhone app off the US storefront (the web stand-in for the
 * native plugin reports no storefront, which is the same answer).
 *
 * The spy is restored after the test (`restoreMocks`).
 */
export const asPhoneThatMayNotSell = () =>
  vi.spyOn(Capacitor, "getPlatform").mockReturnValue("ios");
