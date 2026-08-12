/**
 * Who wrote a listing — always said together with how the listing got here.
 *
 * A name on its own cannot answer "who wrote this?", because three different
 * trust stories print the same string: code shipped in this build, a listing a
 * trusted registry signed, and a file someone's administrator dropped in. So
 * the author is never rendered alone. The source picks the sentence, the name
 * is interpolated into it as claimed, and an unverified listing naming a
 * first-party author still reads "added by your administrator".
 *
 * One component for the card, the detail page and the install dialog, so the
 * three cannot answer the question differently.
 */

import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

/**
 * The fields provenance reads. Structural rather than the generated summary
 * type, so a browse card, a detail page and a dialog all satisfy it.
 */
export interface ListingAttribution {
  source: string;
  author_name: string;
  author_url?: string | null;
}

export interface ListingProvenanceProps {
  listing: ListingAttribution;
  /**
   * Whether to offer the author's own address alongside the sentence. Off on
   * cards, whose whole surface is already a link to the listing.
   */
  showAuthorUrl?: boolean;
  className?: string;
}

/**
 * The sentence for one listing. Written as an explicit branch per source so the
 * displayed string is readable next to the three cases it implements, and so an
 * unrecognized source falls through to stating the claim and nothing more —
 * never to a trust story this build cannot vouch for.
 */
const provenanceLine = (listing: ListingAttribution, t: TFunction<"marketplace">): string => {
  const author = listing.author_name;
  switch (listing.source) {
    case "builtin":
      // Shipped and reviewed in this repository, so the answer is this build
      // rather than anything the manifest claims.
      return t("provenance.builtin");
    case "registry":
      return t("provenance.registry", { author });
    case "operator":
      return t("provenance.operator", { author });
    default:
      return t("provenance.plain", { author });
  }
};

/**
 * The author's address, only when it is one we will hand a click to.
 *
 * `author_url` is third-party text that arrived in a manifest, so it is treated
 * as a claim: `https:` only, and anything else — another scheme, a relative
 * path, an unparseable string — is shown as text instead.
 */
const linkableUrl = (url: string | null | undefined): string | null => {
  if (!url) return null;
  try {
    return new URL(url).protocol === "https:" ? url : null;
  } catch {
    return null;
  }
};

export function ListingProvenance({
  listing,
  showAuthorUrl = true,
  className,
}: ListingProvenanceProps) {
  const { t } = useTranslation("marketplace");

  const claimedUrl = listing.author_url?.trim() || null;
  const href = linkableUrl(claimedUrl);

  return (
    <p className={cn("text-muted-foreground text-xs", className)}>
      {provenanceLine(listing, t)}
      {showAuthorUrl && claimedUrl && (
        <>
          <span aria-hidden="true"> · </span>
          {href ? (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="underline underline-offset-2 hover:text-foreground"
            >
              {t("provenance.website")}
            </a>
          ) : (
            <span>{claimedUrl}</span>
          )}
        </>
      )}
    </p>
  );
}
