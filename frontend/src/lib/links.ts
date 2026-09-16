/**
 * Where the project's own public pages live — the help center, the source,
 * the releases. One place, so the address is not copied into every surface
 * that points somebody at a guide.
 */

export const REPO_URL = "https://github.com/Morelitea/initiative";
export const RELEASES_URL = `${REPO_URL}/releases`;
export const CHANGELOG_URL = `${REPO_URL}/blob/main/CHANGELOG.md`;

/** The English help center. Built from `docs/en/` and published on `main`. */
export const DOCS_URL = "https://morelitea.github.io/initiative/en/";

/** A page of the help center by its path under `docs/en/`, with or without a
 *  leading slash; a fragment carries through untouched. */
export const docsUrl = (path = ""): string => `${DOCS_URL}${path.replace(/^\//, "")}`;

/**
 * The Android app attached to one release. CI names the file after the
 * version and attaches it only to a release whose native shell changed, which
 * is exactly the release `MIN_NATIVE_VERSION` names — so the server's own
 * floor is the newest app there is for it.
 */
export const androidApkUrl = (version: string): string =>
  `${RELEASES_URL}/download/v${version}/initiative-${version}.apk`;

/** Adds the repo to Obtainium, which then keeps the Android app updated from
 *  its releases. The same link the install guide carries. */
export const OBTAINIUM_URL =
  "https://apps.obtainium.imranr.dev/redirect?r=obtainium%3A%2F%2Fadd%2Fhttps%3A%2F%2Fgithub.com%2FMorelitea%2Finitiative";
