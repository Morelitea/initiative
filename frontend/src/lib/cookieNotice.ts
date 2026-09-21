/**
 * Whether this browser has been shown the notice about what Initiative keeps
 * in it.
 *
 * An acknowledgement rather than a consent record: everything Initiative
 * stores is needed to run the thing you asked for — staying signed in, the
 * theme you picked, what you had open — so there is nothing here to grant or
 * withhold, and nothing changes when the notice is dismissed. It is kept in
 * this browser and goes no further; there is no account behind it, because
 * somebody reading the landing page does not have one.
 */

import { getItem, setItem } from "@/lib/storage";

const STORAGE_KEY = "cookie-notice-seen";

/**
 * Bump when the notice starts saying something materially different — another
 * kind of storage, another company involved. Everyone is shown it once more.
 * The number is which notice was acknowledged, not how many times.
 */
export const COOKIE_NOTICE_VERSION = 1;

export const cookieNoticeSeen = (): boolean =>
  Number.parseInt(getItem(STORAGE_KEY) ?? "", 10) >= COOKIE_NOTICE_VERSION;

export const acknowledgeCookieNotice = (): void =>
  setItem(STORAGE_KEY, String(COOKIE_NOTICE_VERSION));
