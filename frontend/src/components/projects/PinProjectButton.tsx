import type { MouseEvent } from "react";
import { Pin } from "lucide-react";

import { cn } from "@/lib/utils";
import { useProjectPinMutation } from "@/hooks/useProjectPinMutation";

interface PinProjectButtonProps {
  projectId: number;
  isPinned: boolean;
  canPin: boolean;
  className?: string;
  suppressNavigation?: boolean;
  iconSize?: "sm" | "md";
}

const PinGlyph = ({ isPinned }: { isPinned: boolean }) => (
  <Pin
    className={cn("h-4 w-4", isPinned ? "text-primary" : undefined)}
    fill={isPinned ? "currentColor" : "none"}
  />
);

export const PinProjectButton = ({
  projectId,
  isPinned,
  canPin,
  className,
  suppressNavigation = false,
  iconSize = "md",
}: PinProjectButtonProps) => {
  const pinMutation = useProjectPinMutation();
  const pending = pinMutation.isPending && pinMutation.variables?.projectId === projectId;
  const sizeClasses = iconSize === "sm" ? "h-7 w-7" : "h-9 w-9";
  const baseClasses =
    "bg-background text-muted-foreground focus-visible:ring-ring inline-flex items-center justify-center rounded-full border transition focus-visible:ring-2 focus-visible:outline-none";

  const handleClick = (event: MouseEvent<HTMLButtonElement>) => {
    if (!canPin) {
      return;
    }
    if (suppressNavigation) {
      event.preventDefault();
      event.stopPropagation();
    }
    pinMutation.mutate({ projectId, nextState: !isPinned });
  };

  if (!canPin) {
    return (
      <div
        className={cn(baseClasses, sizeClasses, "cursor-default opacity-70", className)}
        role="img"
        aria-label={isPinned ? "Pinned project" : "Not pinned"}
        title={isPinned ? "Pinned project" : "Not pinned"}
      >
        <PinGlyph isPinned={isPinned} />
      </div>
    );
  }

  return (
    <button
      type="button"
      className={cn(
        baseClasses,
        sizeClasses,
        "hover:text-primary disabled:opacity-60",
        className
      )}
      aria-pressed={isPinned}
      aria-label={isPinned ? "Unpin project" : "Pin project"}
      disabled={pending}
      onClick={handleClick}
    >
      <PinGlyph isPinned={isPinned} />
    </button>
  );
};
