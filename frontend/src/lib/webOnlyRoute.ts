import { redirect } from "@tanstack/react-router";

/** Sends an app package to sign-in; the website goes on to the page. */
export const signInInApp = (inApp: boolean) => {
  if (inApp) throw redirect({ to: "/login" });
};

/**
 * The public front pages (welcome, pricing, download, what's new) belong to
 * the website. The app packages open straight to sign-in, so in a Capacitor
 * build these routes send the reader there instead, and each route leaves its
 * page out of the bundle by choosing its component on the same build flag.
 */
export const leaveForSignIn = () => signInInApp(__IS_CAPACITOR__);

/** The component a web-only route renders in an app package: none. */
export const NotInApp = () => null;
