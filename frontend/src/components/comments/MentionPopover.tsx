import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckSquare, FileText, FolderKanban, User } from "lucide-react";

import { apiClient } from "@/api/client";
import { Command, CommandGroup, CommandItem, CommandList } from "@/components/ui/command";
import type { MentionEntityType, MentionSuggestion } from "@/types/api";

interface MentionPopoverProps {
  type: MentionEntityType;
  query: string;
  initiativeId: number;
  onSelect: (suggestion: MentionSuggestion) => void;
  onClose: () => void;
  position: { top: number; left: number };
}

const fetchSuggestions = async (
  type: MentionEntityType,
  initiativeId: number,
  query: string
): Promise<MentionSuggestion[]> => {
  const response = await apiClient.get<MentionSuggestion[]>("/comments/mentions/search", {
    params: {
      entity_type: type,
      initiative_id: initiativeId,
      q: query,
    },
  });
  return response.data;
};

const getIcon = (type: MentionEntityType) => {
  switch (type) {
    case "user":
      return <User className="h-4 w-4" />;
    case "task":
      return <CheckSquare className="h-4 w-4" />;
    case "doc":
      return <FileText className="h-4 w-4" />;
    case "project":
      return <FolderKanban className="h-4 w-4" />;
  }
};

const getTypeLabel = (type: MentionEntityType) => {
  switch (type) {
    case "user":
      return "Users";
    case "task":
      return "Tasks";
    case "doc":
      return "Documents";
    case "project":
      return "Projects";
  }
};

export const MentionPopover = ({
  type,
  query,
  initiativeId,
  onSelect,
  onClose,
  position,
}: MentionPopoverProps) => {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const popoverRef = useRef<HTMLDivElement>(null);

  const { data: suggestions = [], isLoading } = useQuery({
    queryKey: ["mentionSuggestions", type, initiativeId, query],
    queryFn: () => fetchSuggestions(type, initiativeId, query),
    staleTime: 30000,
  });

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
          setSelectedIndex((prev) => (prev + 1) % suggestions.length);
          break;
        case "ArrowUp":
          e.preventDefault();
          setSelectedIndex((prev) => (prev - 1 + suggestions.length) % suggestions.length);
          break;
        case "Enter":
          e.preventDefault();
          if (suggestions[selectedIndex]) {
            onSelect(suggestions[selectedIndex]);
          }
          break;
        case "Escape":
          e.preventDefault();
          onClose();
          break;
      }
    },
    [suggestions, selectedIndex, onSelect, onClose]
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
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
        className="bg-popover text-popover-foreground absolute z-50 w-64 rounded-md border p-2 shadow-md"
        style={{ top: position.top, left: position.left }}
      >
        <p className="text-muted-foreground text-sm">Loading...</p>
      </div>
    );
  }

  if (!suggestions.length) {
    return (
      <div
        ref={popoverRef}
        className="bg-popover text-popover-foreground absolute z-50 w-64 rounded-md border p-2 shadow-md"
        style={{ top: position.top, left: position.left }}
      >
        <p className="text-muted-foreground text-sm">No {getTypeLabel(type).toLowerCase()} found</p>
      </div>
    );
  }

  return (
    <div
      ref={popoverRef}
      className="bg-popover text-popover-foreground absolute z-50 w-64 rounded-md border shadow-md"
      style={{ top: position.top, left: position.left }}
    >
      <Command>
        <CommandList>
          <CommandGroup heading={getTypeLabel(type)}>
            {suggestions.map((suggestion, index) => (
              <CommandItem
                key={`${suggestion.type}-${suggestion.id}`}
                onSelect={() => onSelect(suggestion)}
                className={`flex cursor-pointer items-center gap-2 ${
                  index === selectedIndex ? "bg-accent" : ""
                }`}
              >
                {getIcon(suggestion.type)}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{suggestion.display_text}</p>
                  {suggestion.subtitle && (
                    <p className="text-muted-foreground truncate text-xs">{suggestion.subtitle}</p>
                  )}
                </div>
              </CommandItem>
            ))}
          </CommandGroup>
        </CommandList>
      </Command>
    </div>
  );
};
