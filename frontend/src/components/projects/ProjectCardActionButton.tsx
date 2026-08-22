import type { LucideIcon } from "lucide-react";
import type { MouseEvent } from "react";

import { cn } from "@/lib/utils";

interface ProjectCardActionButtonProps {
  icon: LucideIcon;
  /** Accessible name and hover title — the button itself is icon-only. */
  label: string;
  onClick: () => void;
  disabled?: boolean;
  iconSize?: "sm" | "md";
  className?: string;
}

/**
 * Round icon button for a project card's top-right cluster, matching the pin
 * and favorite controls. Cards are wrapped in a link, so the click never
 * bubbles into navigation.
 */
export const ProjectCardActionButton = ({
  icon: Icon,
  label,
  onClick,
  disabled = false,
  iconSize = "md",
  className,
}: ProjectCardActionButtonProps) => {
  const handleClick = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    onClick();
  };

  return (
    <button
      type="button"
      className={cn(
        "inline-flex items-center justify-center rounded-full border bg-background text-muted-foreground transition hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60",
        iconSize === "sm" ? "h-7 w-7" : "h-9 w-9",
        className
      )}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={handleClick}
    >
      <Icon className="h-4 w-4" />
    </button>
  );
};
