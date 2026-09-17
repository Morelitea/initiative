/**
 * The mark on a sign-in button, and on its row in the registry.
 *
 * `AuthProvider.icon` holds a key, set from the preset a provider was made
 * from and carried on every save. This is the one place that turns a key into
 * something to draw, so the preset grid, the registry rows and the sign-in
 * buttons all show the same thing.
 *
 * Marks are our own files under `src/assets/idp/`, the arrangement the import
 * page already uses for `todoist.svg` and the rest: a local file, imported as
 * a URL, drawn in an `<img>`. Nothing is fetched from anybody's CDN.
 *
 * Adding one: drop `<key>.svg` in that folder, import it below, and add the
 * entry. A key with no file gets the fallback, so a provider is never broken
 * by a missing mark — it just reads as its name, which is most of the job.
 */

import type { LucideIcon } from "lucide-react";
import { KeyRound } from "lucide-react";

/**
 * Key → mark. Populated as the files land; see the note above.
 *
 * Deliberately empty rather than pointed at brand marks we have not drawn:
 * a wrong logo beside a provider's name is worse than none, and Vite fails
 * the build on an import that is not there.
 */
export const PROVIDER_ICONS: Record<string, string> = {};

/** Stands in until a provider has a mark of its own. */
export const FALLBACK_PROVIDER_ICON: LucideIcon = KeyRound;

export const providerIconUrl = (icon: string | null | undefined): string | null =>
  (icon && PROVIDER_ICONS[icon]) || null;
