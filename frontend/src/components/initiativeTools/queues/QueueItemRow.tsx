import { EyeOff, FileText, ListChecks, PauseCircle } from "lucide-react";
import type { KeyboardEvent, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { QueueItemRead } from "@/api/generated/initiativeAPI.schemas";
import { TagBadge } from "@/components/tags/TagBadge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { getInitials } from "@/lib/initials";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { cn } from "@/lib/utils";

interface QueueItemRowProps {
  item: QueueItemRead;
  isActive: boolean;
  onEdit: (item: QueueItemRead) => void;
  onSetActive: (itemId: number) => void;
  /**
   * Optional control rendered to the right of the row (e.g. the "Act" button
   * on a held row). The row was historically a `<button>` element, but a
   * button-inside-button is invalid HTML; the root is now a `<div
   * role="button">` so this slot can contain interactive children safely.
   */
  actionButton?: ReactNode;
}

export const QueueItemRow = ({
  item,
  isActive,
  onEdit,
  onSetActive,
  actionButton,
}: QueueItemRowProps) => {
  const { t } = useTranslation("queues");

  const userInitials = item.user ? getInitials(item.user.full_name, item.user.email) : null;
  const userAvatarSrc = item.user
    ? resolveUploadUrl(item.user.avatar_url) || item.user.avatar_base64 || undefined
    : undefined;
  const isHeld = item.held_at_round !== null;

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onEdit(item);
    }
  };

  return (
    // biome-ignore lint/a11y/useSemanticElements: a native <button> would make
    // nested interactive children (the Act button on held rows) invalid HTML.
    <div
      role="button"
      tabIndex={0}
      onClick={() => onEdit(item)}
      onDoubleClick={() => onSetActive(item.id)}
      onKeyDown={handleKeyDown}
      className={cn(
        "group flex w-full items-center gap-3 rounded-lg border px-4 py-3 text-left transition",
        "hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        isActive && "border-primary bg-primary/5 ring-1 ring-primary/20"
      )}
    >
      {/* Position number */}
      <div className="w-10 shrink-0 text-center font-medium font-mono text-muted-foreground text-sm">
        {item.position}
      </div>

      {/* Color dot */}
      {item.color && (
        <span
          className="h-3 w-3 shrink-0 rounded-full border"
          style={{ backgroundColor: item.color }}
          aria-hidden="true"
        />
      )}

      {/* Label and details */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className={cn("truncate font-medium", isActive && "text-primary")}>
            {item.label}
          </span>
          {isActive && (
            <span className="rounded-full bg-primary px-2 py-0.5 font-medium text-primary-foreground text-xs">
              {t("currentTurn")}
            </span>
          )}
          {isHeld && (
            <PauseCircle
              className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
              aria-label={t("held")}
            />
          )}
          {!item.is_visible && (
            <EyeOff
              className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
              aria-label={t("hidden")}
            />
          )}
        </div>

        {/* User name */}
        {item.user && (
          <p className="mt-0.5 text-muted-foreground text-xs">
            {item.user.full_name || item.user.email}
          </p>
        )}

        {/* Tags */}
        {item.tags.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {item.tags.slice(0, 4).map((tag) => (
              <TagBadge key={tag.id} tag={tag} size="sm" />
            ))}
            {item.tags.length > 4 && (
              <span className="text-muted-foreground text-xs">+{item.tags.length - 4}</span>
            )}
          </div>
        )}

        {/* Notes preview */}
        {item.notes && (
          <p className="mt-1 line-clamp-1 text-muted-foreground text-xs">{item.notes}</p>
        )}
      </div>

      {/* Linked entity badges */}
      <div className="flex shrink-0 items-center gap-1.5">
        {item.documents.length > 0 && (
          <Badge variant="secondary" className="gap-1 px-1.5 py-0.5 text-xs">
            <FileText className="h-3 w-3" />
            {item.documents.length}
          </Badge>
        )}
        {item.tasks.length > 0 && (
          <Badge variant="secondary" className="gap-1 px-1.5 py-0.5 text-xs">
            <ListChecks className="h-3 w-3" />
            {item.tasks.length}
          </Badge>
        )}
      </div>

      {/* User avatar */}
      {item.user && (
        <Avatar className="h-7 w-7 shrink-0">
          {userAvatarSrc ? (
            <AvatarImage src={userAvatarSrc} alt={item.user.full_name ?? ""} />
          ) : null}
          <AvatarFallback userId={item.user.id} className="text-xs">
            {userInitials}
          </AvatarFallback>
        </Avatar>
      )}

      {/* Right-side action button (e.g. Act on held rows) */}
      {actionButton}
    </div>
  );
};
