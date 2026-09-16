/** Which download the visitor most likely wants, read off the browser. */
export type VisitorPlatform = "android" | "ios" | "desktop";

export function detectPlatform(
  nav: Pick<Navigator, "userAgent" | "maxTouchPoints"> = navigator
): VisitorPlatform {
  const ua = nav.userAgent;
  if (/android/i.test(ua)) return "android";
  if (/iphone|ipad|ipod/i.test(ua)) return "ios";
  // iPadOS Safari presents itself as a Mac; the touch points give it away.
  if (/macintosh/i.test(ua) && nav.maxTouchPoints > 1) return "ios";
  return "desktop";
}
