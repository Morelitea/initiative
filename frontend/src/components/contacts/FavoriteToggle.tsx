import { Star } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface FavoriteToggleProps {
  starred: boolean;
  onToggle: () => void;
  /** The person, so the label says who is being starred. */
  name: string;
  disabled?: boolean;
}

/**
 * The star on a contact row.
 *
 * Starring is private and one-directional — the other person is never told —
 * so there is nothing to confirm in either direction. Unstarring is immediate
 * too: re-adding is one click on a row still on the page.
 */
export const FavoriteToggle = ({ starred, onToggle, name, disabled }: FavoriteToggleProps) => {
  const { t } = useTranslation("contacts");
  const label = starred ? t("unfavorite", { name }) : t("favorite", { name });

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="size-8 shrink-0"
      aria-pressed={starred}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={(event) => {
        // The row is a link to the profile; the star is not a way there.
        event.preventDefault();
        event.stopPropagation();
        onToggle();
      }}
    >
      <Star
        className={cn(
          "size-4",
          starred ? "fill-amber-400 text-amber-500" : "text-muted-foreground"
        )}
      />
    </Button>
  );
};
