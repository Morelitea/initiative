import { X } from "lucide-react";

import { cn } from "@/lib/utils";
import type { TagSummary } from "@/types/api";

/**
 * Calculate relative luminance from a hex color.
 * Returns a value between 0 (darkest) and 1 (lightest).
 */
function getLuminance(hex: string): number {
  const rgb = hex
    .replace("#", "")
    .match(/.{2}/g)
    ?.map((c) => {
      const value = parseInt(c, 16) / 255;
      return value <= 0.03928 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4);
    });

  if (!rgb || rgb.length < 3) return 0;
  return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
}

/**
 * Get contrasting text color (black or white) based on background luminance.
 */
function getContrastColor(bgColor: string): string {
  return getLuminance(bgColor) > 0.4 ? "#000000" : "#FFFFFF";
}

interface TagBadgeProps {
  tag: TagSummary;
  onClick?: () => void;
  onRemove?: () => void;
  size?: "sm" | "md";
  className?: string;
}

export function TagBadge({ tag, onClick, onRemove, size = "sm", className }: TagBadgeProps) {
  const textColor = getContrastColor(tag.color);
  const isClickable = !!onClick;

  return (
    <span
      role={isClickable ? "button" : undefined}
      tabIndex={isClickable ? 0 : undefined}
      onClick={isClickable ? onClick : undefined}
      onKeyDown={
        isClickable
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick?.();
              }
            }
          : undefined
      }
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded-md font-medium",
        size === "sm" && "px-1.5 py-0.5 text-xs",
        size === "md" && "px-2 py-1 text-sm",
        isClickable && "cursor-pointer hover:opacity-80",
        className
      )}
      style={{
        backgroundColor: tag.color,
        color: textColor,
      }}
    >
      <span className="truncate">{tag.name}</span>
      {onRemove && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="ml-0.5 rounded-sm hover:opacity-70 focus:outline-none"
          aria-label={`Remove ${tag.name} tag`}
        >
          <X className={cn(size === "sm" ? "h-3 w-3" : "h-4 w-4")} />
        </button>
      )}
    </span>
  );
}
