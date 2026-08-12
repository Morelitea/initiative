/**
 * Who wrote a listing.
 *
 * Every app on a deployment is there because an administrator put it there —
 * they choose the registry to trust, the files to drop in, and the apps to
 * install. So the question a user has before installing is authorship, not
 * approval, and this renders exactly that: the author, as claimed, with
 * first-party listings named as ours.
 *
 * Deliberately not a trust gradient. Ranking listings by where they came from
 * would imply some of them arrived without the administrator's say-so, which is
 * not a state this platform has. What keeps the claim honest is enforcement
 * rather than a badge: `core.*` is reserved to listings shipped in this
 * repository, and a registry's index is signature-checked against a key the
 * deployment configured before any listing in it is read.
 *
 * One component for the card, the detail page and the install dialog, so the
 * three cannot answer the question differently.
 */

import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

/**
 * The fields attribution reads. Structural rather than the generated summary
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
   * Whether to offer the author's own address alongside the name. Off on cards,
   * whose whole surface is already a link to the listing.
   */
  showAuthorUrl?: boolean;
  className?: string;
}

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
  // Listings shipped in this repository are named as ours rather than by
  // whatever their manifest says, since `core.*` is reserved and the answer
  // there is this build.
  const line =
    listing.source === "builtin"
      ? t("provenance.builtin")
      : t("provenance.plain", { author: listing.author_name });

  return (
    <p className={cn("text-muted-foreground text-xs", className)}>
      {line}
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
