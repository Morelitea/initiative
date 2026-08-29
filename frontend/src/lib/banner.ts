/**
 * A guild's banner, as the client renders it.
 *
 * The banner is one value — the picture, the fill under it, the colour the
 * copy is written in, where that copy sits, and how the banner ends — so it
 * travels as one, from the payload into `PageBanner` and the things that sit
 * on the banner beside it.
 */

import type { GuildBannerRead } from "@/api/generated/initiativeAPI.schemas";
import { readableTextColor } from "@/lib/contrastColor";
import { resolveHeaderlessApiUrl } from "@/lib/uploadUrl";

/**
 * A banner ready to render: its picture resolved to a URL this client can
 * fetch, and every question answered for a header that has no guild banner to
 * show — one whose guild has not arrived yet, or one that is all fixed
 * artwork. An empty fill is such a header's: it paints nothing rather than
 * guessing at a colour.
 */
export const renderableBanner = (banner?: Partial<GuildBannerRead> | null): GuildBannerRead => ({
  image_url: banner?.image_url ? resolveHeaderlessApiUrl(banner.image_url) : null,
  color: banner?.color ?? "",
  text_color: banner?.text_color ?? readableTextColor(banner?.color ?? ""),
  text_align: banner?.text_align ?? "center",
  fade: banner?.fade ?? "none",
});
