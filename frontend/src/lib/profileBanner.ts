/**
 * A profile's banner, in the shape every other banner on the site travels in.
 *
 * A community front page and the community directory both hand `PageBanner` a
 * `GuildBannerRead`; a profile is the same kind of page and gets the same
 * treatment, so its decoration is translated into that shape here rather than
 * a second banner being written for it.
 *
 * What a community's admin chooses, a decoration declares: the picture is the
 * artwork, the ink is the one the artwork was drawn for, and the fade is
 * always on, because the page below is meant to ride over the tail of it.
 *
 * `null` where there is no artwork, so a profile wearing no banner gets an
 * ordinary page heading rather than a hero over an empty band — a bannerless
 * header has no fill to work its ink out from, and would write in white
 * whatever the theme underneath it is.
 */

import type {
  GuildBannerRead,
  ProfileDecorationsOutput,
} from "@/api/generated/initiativeAPI.schemas";
import { DARK_TEXT, LIGHT_TEXT } from "@/lib/contrastColor";
import { decorationSrc, resolveDecoration } from "@/lib/profileDecorations";

export const profileBanner = (
  decorations: ProfileDecorationsOutput | null | undefined
): GuildBannerRead | null => {
  const banner = resolveDecoration(decorations?.banner, "banner");
  if (!banner) return null;
  return {
    image_url: decorationSrc(banner, decorations?.grad_year),
    color: "",
    text_color: banner.ink === "dark" ? DARK_TEXT : LIGHT_TEXT,
    text_align: "left",
    fade: "strong",
  };
};
