/**
 * That these numbers are not the reader's own.
 *
 * A dashboard publishing over something shows every viewer the same rows,
 * including rows they could not reach anywhere else in the app. A reader has to
 * be able to tell — otherwise a figure they cannot reconcile with what they see
 * elsewhere reads as a bug rather than as a share somebody made deliberately.
 */

import { Eye } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { PublishedOver } from "@/api/generated/initiativeAPI.schemas";

export function PublishedViewNotice({
  published,
  active,
}: {
  published: PublishedOver[];
  /** Whether those grants are serving. A published view rests on its author's
   *  standing access; when that stops the dashboard falls back to each
   *  viewer's own, and saying the figures are shared would then be saying the
   *  opposite of what is happening. */
  active: boolean;
}) {
  const { t } = useTranslation("dashboards");
  if (!published.length || !active) return null;
  return (
    <p className="inline-flex items-center gap-1.5 text-muted-foreground text-xs">
      <Eye className="h-3.5 w-3.5" aria-hidden />
      {t("published.notice", { count: published.length })}
    </p>
  );
}
