import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

/**
 * What the page is doing while a search runs.
 *
 * A search here is not one query: every community keeps its own member list
 * and is visited in turn, so the wait grows with how many communities the
 * reader is in. Saying so is the difference between a page that is slow and a
 * page that looks broken.
 */
export const ContactSearchProgress = () => {
  const { t } = useTranslation("contacts");

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-start gap-3 rounded-lg border bg-muted/40 px-4 py-3"
    >
      <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin text-muted-foreground" />
      <div className="space-y-0.5">
        <p className="font-medium text-sm">{t("searching.title")}</p>
        <p className="max-w-prose text-muted-foreground text-sm">{t("searching.description")}</p>
      </div>
    </div>
  );
};
