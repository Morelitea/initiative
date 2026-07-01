import type { ReactNode } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";

interface SelectableGridItemProps {
  /** Whether the list is in selection mode. When false, children render as-is. */
  active: boolean;
  selected: boolean;
  onToggle: () => void;
  children: ReactNode;
  label?: string;
}

/**
 * Wraps a grid card so it can be multi-selected without touching the card
 * component. In selection mode the card underneath is made non-interactive (its
 * link won't navigate) and a full-card toggle button + checkbox overlay is shown.
 */
export function SelectableGridItem({
  active,
  selected,
  onToggle,
  children,
  label,
}: SelectableGridItemProps) {
  if (!active) return <>{children}</>;

  return (
    <div className="relative">
      {/* `inert` blocks pointer *and* keyboard/AT focus from reaching the card's
          links/buttons while selecting — the overlay is the only interactive part. */}
      <div inert className="select-none">
        {children}
      </div>
      <button
        type="button"
        onClick={onToggle}
        aria-pressed={selected}
        aria-label={label}
        className={cn(
          "absolute inset-0 z-10 rounded-2xl ring-inset transition focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          selected ? "bg-primary/5 ring-2 ring-primary" : "hover:bg-muted/20"
        )}
      >
        <span className="absolute top-3 left-3">
          <Checkbox
            checked={selected}
            className="pointer-events-none border-2 bg-background shadow"
          />
        </span>
      </button>
    </div>
  );
}
