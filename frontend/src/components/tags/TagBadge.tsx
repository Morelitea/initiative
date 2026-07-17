import { Link, useNavigate } from "@tanstack/react-router";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { getContrastingTextColor } from "@/lib/counter-color";
import { cn } from "@/lib/utils";

interface TagBadgeProps {
  tag: TagSummary;
  to?: string;
  /** Set when the badge renders inside a wrapping link (card-as-anchor):
   * navigates programmatically instead of nesting an `<a>` in an `<a>`,
   * and stops the click from also triggering the outer link. */
  nested?: boolean;
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

export function TagBadge({
  tag,
  to,
  nested = false,
  onClick,
  onRemove,
  size = "sm",
  className,
}: TagBadgeProps) {
  const { t } = useTranslation("tags");
  const navigate = useNavigate();
  const handleClick = onClick ?? (to && nested ? () => void navigate({ to }) : undefined);
  // Tags render pure black (not the slate the counter tiles use) on light
  // tag colors — the saturated user-picked backgrounds need the extra contrast.
  const textColor = getContrastingTextColor(tag.color) === "#0F172A" ? "#000000" : "#FFFFFF";
  const isClickable = !!handleClick || !!to;

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

  if (to && !nested) {
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
    // biome-ignore lint/a11y/noStaticElementInteractions: Only add onClick if it's interactive, and handle keyboard events for accessibility
    <span
      role={isClickable ? "button" : undefined}
      tabIndex={isClickable ? 0 : undefined}
      onClick={
        handleClick
          ? (e) => {
              e.preventDefault();
              e.stopPropagation();
              handleClick();
            }
          : undefined
      }
      onKeyDown={
        handleClick
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                e.stopPropagation();
                handleClick();
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
