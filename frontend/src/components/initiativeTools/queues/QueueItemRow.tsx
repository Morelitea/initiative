import { EyeOff, FileText, ListChecks } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { TagBadge } from "@/components/tags/TagBadge";
import { cn } from "@/lib/utils";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import type { QueueItemRead } from "@/api/generated/initiativeAPI.schemas";

interface QueueItemRowProps {
  item: QueueItemRead;
  isActive: boolean;
  onEdit: (item: QueueItemRead) => void;
  onSetActive: (itemId: number) => void;
}

export const QueueItemRow = ({ item, isActive, onEdit, onSetActive }: QueueItemRowProps) => {
  const { t } = useTranslation("queues");

  const userInitials = item.user
    ? (item.user.full_name ?? item.user.email ?? "U")
        .split(/\s+/)
        .map((part) => part.charAt(0).toUpperCase())
        .join("")
        .slice(0, 2)
    : null;

  return (
    <button
      type="button"
      onClick={() => onEdit(item)}
      onDoubleClick={() => onSetActive(item.id)}
      className={cn(
        "group flex w-full items-center gap-3 rounded-lg border px-4 py-3 text-left transition",
        "hover:bg-accent/50 focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none",
        isActive && "border-primary bg-primary/5 ring-primary/20 ring-1"
      )}
    >
      {/* Position number */}
      <div className="text-muted-foreground w-10 shrink-0 text-center font-mono text-sm font-medium">
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
            <span className="bg-primary text-primary-foreground rounded-full px-2 py-0.5 text-xs font-medium">
              {t("currentTurn")}
            </span>
          )}
          {!item.is_visible && (
            <EyeOff
              className="text-muted-foreground h-3.5 w-3.5 shrink-0"
              aria-label={t("hidden")}
            />
          )}
        </div>

        {/* User name */}
        {item.user && (
          <p className="text-muted-foreground mt-0.5 text-xs">
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
          <p className="text-muted-foreground mt-1 line-clamp-1 text-xs">{item.notes}</p>
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
          <AvatarImage
            src={resolveUploadUrl(item.user.avatar_url) ?? undefined}
            alt={item.user.full_name ?? ""}
          />
          <AvatarFallback className="text-xs">{userInitials}</AvatarFallback>
        </Avatar>
      )}
    </button>
  );
};
