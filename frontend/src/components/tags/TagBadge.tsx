import { useTranslation } from "react-i18next";
import { Link } from "@tanstack/react-router";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";
import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";

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
  to?: string;
  onClick?: () => void;
  onRemove?: () => void;
  size?: "sm" | "md";
  className?: string;
}

const MAX_SEGMENT_LENGTH = 12;

function truncateSegment(segment: string, maxLength: number): string {
  if (segment.length <= maxLength) return segment;
  return segment.slice(0, maxLength - 3) + "...";
}

export function TagBadge({ tag, to, onClick, onRemove, size = "sm", className }: TagBadgeProps) {
  const { t } = useTranslation("tags");
  const textColor = getContrastColor(tag.color);
  const isClickable = !!onClick || !!to;

  // Truncate each segment individually (e.g., "long-name/a" -> "long-na.../a")
  const segments = tag.name.split("/");
  const displayName = segments.map((s) => truncateSegment(s, MAX_SEGMENT_LENGTH)).join("/");

  const sharedClassName = cn(
    "inline-flex max-w-full items-center gap-1 rounded-md font-medium",
    size === "sm" && "px-1.5 py-0.5 text-xs",
    size === "md" && "px-2 py-1 text-sm",
    isClickable && "cursor-pointer hover:opacity-80",
    className
  );

  const sharedStyle = {
    backgroundColor: tag.color,
    color: textColor,
  };

  const removeButton = onRemove ? (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        e.preventDefault();
        onRemove();
      }}
      className="ml-0.5 rounded-sm hover:opacity-70 focus:outline-none"
      aria-label={t("badge.remove", { name: tag.name })}
    >
      <X className={cn(size === "sm" ? "h-3 w-3" : "h-4 w-4")} />
    </button>
  ) : null;

  if (to) {
    // When onRemove is also set, wrap in a span so the button isn't nested inside the link
    if (removeButton) {
      return (
        <span className={sharedClassName} style={sharedStyle} title={tag.name}>
          <Link to={to} className="truncate hover:underline">
            {displayName}
          </Link>
          {removeButton}
        </span>
      );
    }
    return (
      <Link to={to} className={sharedClassName} style={sharedStyle} title={tag.name}>
        <span className="truncate">{displayName}</span>
      </Link>
    );
  }

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
      className={sharedClassName}
      style={sharedStyle}
      title={tag.name}
    >
      <span className="truncate">{displayName}</span>
      {removeButton}
    </span>
  );
}
