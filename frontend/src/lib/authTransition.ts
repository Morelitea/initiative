/**
 * Bridges the one-render gap between an in-SPA sign-in completing and the
 * auth context committing the new user, so the authenticated-route guard
 * doesn't bounce the fresh session to the welcome screen. Deliberately an
 * in-memory marker, not a URL param: it can't linger in the address bar,
 * survive a share/bookmark, or hold the guard open after logout. Time-boxed
 * as a backstop and cleared explicitly on logout.
 */
const WINDOW_MS = 5000;

let justSignedInUntil = 0;

export const markJustSignedIn = () => {
  justSignedInUntil = Date.now() + WINDOW_MS;
};

export const clearJustSignedIn = () => {
  justSignedInUntil = 0;
};

export const isJustSignedIn = () => Date.now() < justSignedInUntil;
