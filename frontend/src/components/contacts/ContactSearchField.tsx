import { Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface ContactSearchFieldProps {
  /** The committed term, which lives in the URL. */
  value: string;
  onChange: (next: string) => void;
}

/** How long typing settles before both reads are refetched. */
const DEBOUNCE_MS = 250;

/**
 * One field over the whole page.
 *
 * The term is answered by the server rather than filtered here, because a
 * section only holds a page of its community at a time — a match further down
 * a roster is not on the client to filter.
 */
export const ContactSearchField = ({ value, onChange }: ContactSearchFieldProps) => {
  const { t } = useTranslation("contacts");
  const [draft, setDraft] = useState(value);

  // Follow the URL when it changes from outside (back/forward, a shared link).
  useEffect(() => setDraft(value), [value]);

  useEffect(() => {
    if (draft === value) return;
    const timer = setTimeout(() => onChange(draft), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [draft, value, onChange]);

  return (
    <div className="relative">
      <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        type="search"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder={t("searchPlaceholder")}
        aria-label={t("searchLabel")}
        // The field carries its own clear button; the one the browser draws
        // for a search input would sit beside it saying the same thing.
        className="pr-9 pl-9 [&::-webkit-search-cancel-button]:appearance-none"
      />
      {draft ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="absolute top-1/2 right-1 size-7 -translate-y-1/2"
          aria-label={t("clearSearch")}
          onClick={() => setDraft("")}
        >
          <X className="size-4" />
        </Button>
      ) : null}
    </div>
  );
};
