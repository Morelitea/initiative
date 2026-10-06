/**
 * The mark a file draws when it has no picture of its own.
 *
 * A file is not one sort of thing: a spreadsheet, a whiteboard, a PDF and a
 * link to Figma are all files, and drawing them all as a scroll says nothing
 * about which is which. The rule was written into the file card; it is here
 * so the relations card can obey the same one rather than a copy of it that
 * drifts.
 */

import {
  FileCode,
  FileSpreadsheet,
  FileText,
  ImageIcon,
  type LucideIcon,
  PenTool,
  Presentation,
  ScrollText,
  Sheet,
} from "lucide-react";
import type { ComponentType } from "react";

import { getFileTypeLabel } from "@/lib/fileUtils";
import { matchSmartLinkProvider } from "@/lib/smartLinkProviders";

/** The four facts that decide the mark. Every surface carrying a file has
 *  these, under these names — a summary, a recent item, a link's far end. */
export interface FileFacets {
  file_type?: string | null;
  mime_type?: string | null;
  original_filename?: string | null;
  smart_link_url?: string | null;
}

/** Both a Lucide icon and a provider's brand mark satisfy this. */
export type FileMark = ComponentType<{ className?: string }>;

/**
 * Return the color class for a file icon based on its type.
 * For uploaded files, the color depends on the file format; native docs
 * get the default muted foreground.
 */
function getFileIconColor(
  fileType: string | null | undefined,
  mimeType: string | null | undefined,
  filename: string | null | undefined
): string {
  if (fileType === "whiteboard") return "text-purple-500";
  if (fileType === "spreadsheet") return "text-emerald-500";
  if (fileType !== "file") return "text-muted-foreground";
  const label = getFileTypeLabel(mimeType, filename);
  switch (label) {
    case "PDF":
      return "text-red-500";
    case "Word":
      return "text-blue-600";
    case "Excel":
      return "text-green-600";
    case "PowerPoint":
      return "text-orange-500";
    case "Text":
      return "text-gray-500";
    case "HTML":
      return "text-purple-500";
    case "Image":
      return "text-emerald-500";
    case "Markdown":
      return "text-indigo-500";
    default:
      return "text-muted-foreground";
  }
}

/**
 * Return the Lucide icon component for a file.
 * Native files get ScrollText; uploaded files get a format-specific icon.
 */
function getFileIcon(
  fileType: string | null | undefined,
  mimeType: string | null | undefined,
  filename: string | null | undefined
): LucideIcon {
  if (fileType === "whiteboard") return PenTool;
  if (fileType === "spreadsheet") return Sheet;
  if (fileType !== "file") return ScrollText;
  const label = getFileTypeLabel(mimeType, filename);
  if (label === "Image") return ImageIcon;
  if (label === "Markdown") return FileCode;
  if (label === "Excel") return FileSpreadsheet;
  if (label === "PowerPoint") return Presentation;
  return FileText;
}

/**
 * The icon and its colour class.
 *
 * A smart link whose URL is recognised shows that provider's brand mark; the
 * registry falls back to a generic link for a URL it does not know, which still
 * beats the scroll `getFileIcon` would give a smart link.
 */
export const fileIcon = (facets: FileFacets): { Icon: FileMark; colorClass: string } => {
  const provider =
    facets.file_type === "smart_link" && facets.smart_link_url
      ? matchSmartLinkProvider(facets.smart_link_url)
      : null;
  if (provider) {
    return { Icon: provider.icon, colorClass: "text-muted-foreground" };
  }
  return {
    Icon: getFileIcon(facets.file_type, facets.mime_type, facets.original_filename),
    colorClass: getFileIconColor(facets.file_type, facets.mime_type, facets.original_filename),
  };
};
