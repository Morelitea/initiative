import { Link } from "@tanstack/react-router";
import { Store } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { useGuildPath } from "@/lib/guildUrl";
import { toolListingKind } from "@/lib/tools";

type BrowseMarketplaceButtonProps = {
  /** Whose shelf to open. A tool with no listing kind renders nothing, so a
   *  list can offer the button unconditionally. */
  tool: Tool;
  /** Full-height variant for an empty state, where it sits beside the page's
   *  own "create your first…" button rather than in the toolbar. */
  size?: "sm" | "default";
};

/**
 * "Browse the marketplace", next to the create button rather than behind the
 * overflow menu: adding a ready-made one is the same kind of answer as making
 * one from scratch, and a reader who never opens the overflow menu never
 * learns the shelf is there.
 *
 * In the toolbar it goes in `trailing`, not `actions` — `actions` is hidden
 * below `sm`, where the bottom-nav add pill stands in for create but has no
 * equivalent for this. The label collapses to the icon at that width so the
 * row still fits on one line.
 */
export const BrowseMarketplaceButton = ({ tool, size = "sm" }: BrowseMarketplaceButtonProps) => {
  const { t } = useTranslation("marketplace");
  const gp = useGuildPath();
  const kind = toolListingKind(tool);

  if (!kind) return null;

  const label = t("browse");
  return (
    <Button variant="outline" size={size} className={size === "sm" ? "h-9" : undefined} asChild>
      <Link to={gp("/marketplace")} search={{ kind }} aria-label={label} title={label}>
        <Store className="h-4 w-4" />
        <span className={size === "sm" ? "hidden sm:inline" : undefined}>{label}</span>
      </Link>
    </Button>
  );
};
