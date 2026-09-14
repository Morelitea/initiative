/**
 * The mark a document draws when it has no picture of its own.
 *
 * A document is not one sort of thing: a spreadsheet, a whiteboard, a PDF and a
 * link to Figma are all documents, and drawing them all as a scroll says nothing
 * about which is which. The rule was written into the document card; it is here
 * so the relations card can obey the same one rather than a copy of it that
 * drifts.
 */

import type { ComponentType } from "react";

import { getDocumentIcon, getDocumentIconColor } from "@/lib/fileUtils";
import { matchSmartLinkProvider } from "@/lib/smartLinkProviders";

/** The four facts that decide the mark. Every surface carrying a document has
 *  these, under these names — a summary, a recent item, a link's far end. */
export interface DocumentFacets {
  document_type?: string | null;
  mime_type?: string | null;
  original_filename?: string | null;
  smart_link_url?: string | null;
}

/** Both a Lucide icon and a provider's brand mark satisfy this. */
export type DocumentMark = ComponentType<{ className?: string }>;

/**
 * The icon and its colour class.
 *
 * A smart link whose URL is recognised shows that provider's brand mark; the
 * registry falls back to a generic link for a URL it does not know, which still
 * beats the scroll `getDocumentIcon` would give a smart link.
 */
export const documentIcon = (
  facets: DocumentFacets
): { Icon: DocumentMark; colorClass: string } => {
  const provider =
    facets.document_type === "smart_link" && facets.smart_link_url
      ? matchSmartLinkProvider(facets.smart_link_url)
      : null;
  if (provider) {
    return { Icon: provider.icon, colorClass: "text-muted-foreground" };
  }
  return {
    Icon: getDocumentIcon(facets.document_type, facets.mime_type, facets.original_filename),
    colorClass: getDocumentIconColor(
      facets.document_type,
      facets.mime_type,
      facets.original_filename
    ),
  };
};
