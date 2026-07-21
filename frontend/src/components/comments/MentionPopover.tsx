import { CheckSquare, FileText, FolderKanban } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { MentionEntityType, MentionSuggestion } from "@/api/generated/initiativeAPI.schemas";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useMentionSuggestions } from "@/hooks/useComments";
import { getInitials } from "@/lib/initials";
import { getAvatarSrc } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

interface MentionPopoverProps {
  type: MentionEntityType;
  query: string;
  initiativeId: number;
  /** Pixel anchor (relative to the field) so the popover sits under the word
   *  being typed. Falls back to below the whole field when absent. */
  anchor?: { top: number; left: number } | null;
  onSelect: (suggestion: MentionSuggestion) => void;
  onClose: () => void;
}

// User suggestions render a face (parity with the member typeaheads); the
// other entity types render their type icon.
const renderLeading = (suggestion: MentionSuggestion) => {
  if (suggestion.type === "user") {
    const src = getAvatarSrc(suggestion);
    return (
      <Avatar className="h-5 w-5 shrink-0 text-[10px]">
        {src ? <AvatarImage src={src} alt={suggestion.display_text} /> : null}
        <AvatarFallback userId={suggestion.id}>
          {getInitials(suggestion.display_text)}
        </AvatarFallback>
      </Avatar>
    );
  }
  switch (suggestion.type) {
    case "task":
      return <CheckSquare className="h-4 w-4 shrink-0" />;
    case "doc":
      return <FileText className="h-4 w-4 shrink-0" />;
    case "project":
      return <FolderKanban className="h-4 w-4 shrink-0" />;
  }
};

export const MentionPopover = ({
  type,
  query,
  initiativeId,
  anchor,
  onSelect,
  onClose,
}: MentionPopoverProps) => {
  const { t } = useTranslation(["documents", "common"]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Anchor under the caret when we have a position; otherwise drop below the
  // whole field (the legacy fallback).
  const positionClass = anchor ? "" : "top-full left-0 mt-1";
  const positionStyle = anchor ? { top: anchor.top, left: anchor.left } : undefined;

  const typeLabels: Record<MentionEntityType, string> = useMemo(
    () => ({
      user: t("comments.typeUsers"),
      task: t("comments.typeTasks"),
      doc: t("comments.typeDocs"),
      project: t("comments.typeProjects"),
    }),
    [t]
  );

  const { data: suggestions = [], isLoading } = useMentionSuggestions(type, initiativeId, query);

  // Reset selection when suggestions change
  useEffect(() => {
    setSelectedIndex(0);
  }, [suggestions]);

  // Handle keyboard navigation
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!suggestions.length) return;

      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          e.stopPropagation();
          setSelectedIndex((prev) => (prev + 1) % suggestions.length);
          break;
        case "ArrowUp":
          e.preventDefault();
          e.stopPropagation();
          setSelectedIndex((prev) => (prev - 1 + suggestions.length) % suggestions.length);
          break;
        case "Enter":
        case "Tab":
          e.preventDefault();
          e.stopPropagation();
          if (suggestions[selectedIndex]) {
            onSelect(suggestions[selectedIndex]);
          }
          break;
        case "Escape":
          e.preventDefault();
          e.stopPropagation();
          onClose();
          break;
      }
    },
    [suggestions, selectedIndex, onSelect, onClose]
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [handleKeyDown]);

  // Close on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        onClose();
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [onClose]);

  if (isLoading) {
    return (
      <div
        ref={popoverRef}
        style={positionStyle}
        className={cn(
          "absolute z-50 w-64 rounded-md border bg-popover p-2 text-popover-foreground shadow-md",
          positionClass
        )}
      >
        <p className="text-muted-foreground text-sm">{t("common:loading")}</p>
      </div>
    );
  }

  if (!suggestions.length) {
    return (
      <div
        ref={popoverRef}
        style={positionStyle}
        className={cn(
          "absolute z-50 w-64 rounded-md border bg-popover p-2 text-popover-foreground shadow-md",
          positionClass
        )}
      >
        <p className="text-muted-foreground text-sm">
          {t("comments.noResults", { type: typeLabels[type].toLowerCase() })}
        </p>
      </div>
    );
  }

  return (
    <div
      ref={popoverRef}
      style={positionStyle}
      className={cn(
        "absolute z-50 w-64 overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md",
        positionClass
      )}
    >
      <div className="px-2 py-1.5 font-medium text-muted-foreground text-xs">
        {typeLabels[type]}
      </div>
      <div className="max-h-48 overflow-y-auto">
        {suggestions.map((suggestion, index) => (
          <button
            key={`${suggestion.type}-${suggestion.id}`}
            type="button"
            onClick={() => onSelect(suggestion)}
            className={`flex w-full cursor-pointer items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-accent ${
              index === selectedIndex ? "bg-accent" : ""
            }`}
          >
            {renderLeading(suggestion)}
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium">{suggestion.display_text}</p>
              {suggestion.subtitle && (
                <p className="truncate text-muted-foreground text-xs">{suggestion.subtitle}</p>
              )}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
};
