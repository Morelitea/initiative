/**
 * The mark on a provider's row, and on its card in the wizard's grid.
 *
 * `AuthProvider.icon` holds a key, set from the preset a provider was made
 * from and carried on every save. This is the one place that turns a key into
 * something to draw, so the grid and the rows show the same thing.
 *
 * The marks come from `@icons-pack/react-simple-icons`, which this app already
 * uses for the smart-link providers. They are single-path silhouettes drawn in
 * `currentColor`, which is why they need no light and dark pair and no file in
 * `src/assets` — the same reason they are preferred here over copying the same
 * paths into local SVGs, where they would drift and need maintaining.
 *
 * Three presets have no mark, because simple-icons carries none: Microsoft
 * Entra ID, Zitadel and Pocket ID. They fall back to the generic key, which
 * reads as the provider's name beside it. To give one a mark, add its SVG to
 * `src/assets/idp/` and a `<key>: YourMark` entry here.
 */

import {
  SiAuth0,
  SiAuthelia,
  SiAuthentik,
  SiGoogle,
  SiKeycloak,
  SiOkta,
  SiOpenid,
} from "@icons-pack/react-simple-icons";
import type { LucideIcon } from "lucide-react";
import { KeyRound } from "lucide-react";

/** What a mark is, either way it was drawn. Both take `className` and colour
 *  themselves from `currentColor`. */
export type ProviderMarkIcon = LucideIcon | typeof SiGoogle;

/** Preset key → mark. Keys are `ProviderPreset.key`. */
export const PROVIDER_ICONS: Record<string, ProviderMarkIcon> = {
  google: SiGoogle,
  okta: SiOkta,
  auth0: SiAuth0,
  keycloak: SiKeycloak,
  authentik: SiAuthentik,
  authelia: SiAuthelia,
  // The generic mark for the standard itself, which is what "any OIDC
  // provider" is choosing.
  custom: SiOpenid,
};

/** Stands in for a provider with no mark of its own. */
export const FALLBACK_PROVIDER_ICON: ProviderMarkIcon = KeyRound;

export const providerIcon = (icon: string | null | undefined): ProviderMarkIcon =>
  (icon && PROVIDER_ICONS[icon]) || FALLBACK_PROVIDER_ICON;
