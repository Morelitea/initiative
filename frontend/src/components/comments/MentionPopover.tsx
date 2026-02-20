import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CheckSquare, FileText, FolderKanban, User } from "lucide-react";

import { useMentionSuggestions } from "@/hooks/useComments";
import type { MentionSuggestion } from "@/api/generated/initiativeAPI.schemas";
import type { MentionEntityType } from "@/types/api";

interface MentionPopoverProps {
  type: MentionEntityType;
  query: string;
  initiativeId: number;
  onSelect: (suggestion: MentionSuggestion) => void;
  onClose: () => void;
}

const getIcon = (type: MentionEntityType) => {
  switch (type) {
    case "user":
      return <User className="h-4 w-4 shrink-0" />;
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
  onSelect,
  onClose,
}: MentionPopoverProps) => {
  const { t } = useTranslation(["documents", "common"]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const popoverRef = useRef<HTMLDivElement>(null);

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
        className="bg-popover text-popover-foreground absolute top-full left-0 z-50 mt-1 w-64 rounded-md border p-2 shadow-md"
      >
        <p className="text-muted-foreground text-sm">{t("common:loading")}</p>
      </div>
    );
  }

  if (!suggestions.length) {
    return (
      <div
        ref={popoverRef}
        className="bg-popover text-popover-foreground absolute top-full left-0 z-50 mt-1 w-64 rounded-md border p-2 shadow-md"
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
      className="bg-popover text-popover-foreground absolute top-full left-0 z-50 mt-1 w-64 overflow-hidden rounded-md border shadow-md"
    >
      <div className="text-muted-foreground px-2 py-1.5 text-xs font-medium">
        {typeLabels[type]}
      </div>
      <div className="max-h-48 overflow-y-auto">
        {suggestions.map((suggestion, index) => (
          <button
            key={`${suggestion.type}-${suggestion.id}`}
            type="button"
            onClick={() => onSelect(suggestion)}
            className={`hover:bg-accent flex w-full cursor-pointer items-center gap-2 px-2 py-1.5 text-left text-sm ${
              index === selectedIndex ? "bg-accent" : ""
            }`}
          >
            {getIcon(suggestion.type as MentionEntityType)}
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium">{suggestion.display_text}</p>
              {suggestion.subtitle && (
                <p className="text-muted-foreground truncate text-xs">{suggestion.subtitle}</p>
              )}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
};
