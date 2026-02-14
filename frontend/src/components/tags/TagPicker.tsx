import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, ChevronDown, Plus, Tag as TagIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { TagBadge } from "./TagBadge";
import { useTags, useCreateTag } from "@/hooks/useTags";
import { cn } from "@/lib/utils";
import type { TagSummary, Tag } from "@/types/api";

const DEFAULT_TAG_COLORS = [
  "#6366F1", // Indigo
  "#8B5CF6", // Violet
  "#EC4899", // Pink
  "#EF4444", // Red
  "#F97316", // Orange
  "#EAB308", // Yellow
  "#22C55E", // Green
  "#14B8A6", // Teal
  "#0EA5E9", // Sky
  "#6B7280", // Gray
];

interface TagPickerProps {
  selectedTags: TagSummary[];
  onChange: (tags: TagSummary[]) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  /** "default" shows tag badges in trigger, "filter" matches Select styling */
  variant?: "default" | "filter";
}

export function TagPicker({
  selectedTags,
  onChange,
  placeholder,
  disabled = false,
  className,
  variant = "default",
}: TagPickerProps) {
  const { t } = useTranslation("tags");
  const resolvedPlaceholder = placeholder ?? t("picker.defaultPlaceholder");
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [newTagName, setNewTagName] = useState("");
  const [newTagColor, setNewTagColor] = useState(DEFAULT_TAG_COLORS[0]);

  const { data: allTags = [], isLoading } = useTags();
  const createTagMutation = useCreateTag();

  const selectedIds = useMemo(() => new Set(selectedTags.map((t) => t.id)), [selectedTags]);

  const filteredTags = useMemo(() => {
    if (!search.trim()) return allTags;
    const searchLower = search.toLowerCase();
    return allTags.filter((tag) => tag.name.toLowerCase().includes(searchLower));
  }, [allTags, search]);

  const exactMatch = useMemo(() => {
    if (!search.trim()) return null;
    return allTags.find((tag) => tag.name.toLowerCase() === search.toLowerCase());
  }, [allTags, search]);

  const canCreateNew = search.trim() && !exactMatch;

  const toggleTag = useCallback(
    (tag: Tag | TagSummary) => {
      if (selectedIds.has(tag.id)) {
        onChange(selectedTags.filter((t) => t.id !== tag.id));
      } else {
        const summary: TagSummary = { id: tag.id, name: tag.name, color: tag.color };
        onChange([...selectedTags, summary]);
      }
    },
    [selectedIds, selectedTags, onChange]
  );

  const handleRemoveTag = useCallback(
    (tagId: number) => {
      onChange(selectedTags.filter((t) => t.id !== tagId));
    },
    [selectedTags, onChange]
  );

  const startCreating = useCallback(() => {
    setNewTagName(search.trim());
    setNewTagColor(DEFAULT_TAG_COLORS[Math.floor(Math.random() * DEFAULT_TAG_COLORS.length)]);
    setIsCreating(true);
  }, [search]);

  const cancelCreating = useCallback(() => {
    setIsCreating(false);
    setNewTagName("");
    setNewTagColor(DEFAULT_TAG_COLORS[0]);
  }, []);

  const handleCreateTag = useCallback(async () => {
    if (!newTagName.trim()) return;

    try {
      const newTag = await createTagMutation.mutateAsync({
        name: newTagName.trim(),
        color: newTagColor,
      });
      // Add the new tag to selection
      const summary: TagSummary = { id: newTag.id, name: newTag.name, color: newTag.color };
      onChange([...selectedTags, summary]);
      cancelCreating();
      setSearch("");
    } catch {
      // Error is handled by the mutation
    }
  }, [newTagName, newTagColor, createTagMutation, selectedTags, onChange, cancelCreating]);

  // Display text for filter variant
  const filterDisplayValue = useMemo(() => {
    if (selectedTags.length === 0) return resolvedPlaceholder;
    if (selectedTags.length === 1) return selectedTags[0].name;
    return t("picker.selected", { count: selectedTags.length });
  }, [selectedTags, resolvedPlaceholder, t]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        {variant === "filter" ? (
          <button
            type="button"
            role="combobox"
            aria-expanded={open}
            disabled={disabled}
            className={cn(
              "border-input ring-offset-background focus:ring-ring flex h-9 w-full items-center justify-between rounded-md border bg-transparent px-3 py-2 text-sm whitespace-nowrap shadow-sm focus:ring-1 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50",
              selectedTags.length === 0 && "text-muted-foreground",
              className
            )}
          >
            <span className="truncate">{filterDisplayValue}</span>
            <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </button>
        ) : (
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={open}
            disabled={disabled}
            className={cn(
              "h-auto min-h-10 w-full justify-start",
              selectedTags.length === 0 && "text-muted-foreground",
              className
            )}
          >
            <TagIcon className="mr-2 h-4 w-4 shrink-0 opacity-50" />
            {selectedTags.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {selectedTags.map((tag) => (
                  <TagBadge
                    key={tag.id}
                    tag={tag}
                    size="sm"
                    onRemove={() => handleRemoveTag(tag.id)}
                  />
                ))}
              </div>
            ) : (
              <span>{resolvedPlaceholder}</span>
            )}
          </Button>
        )}
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0" align="start">
        {isCreating ? (
          <div className="space-y-3 p-3">
            <div className="text-sm font-medium">{t("picker.createHeading")}</div>
            <Input
              placeholder={t("picker.namePlaceholder")}
              value={newTagName}
              onChange={(e) => setNewTagName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void handleCreateTag();
                } else if (e.key === "Escape") {
                  cancelCreating();
                }
              }}
              autoFocus
            />
            <ColorPickerPopover
              value={newTagColor}
              onChange={setNewTagColor}
              triggerLabel="Color"
              className="h-9"
            />
            <div className="flex gap-2">
              <Button
                size="sm"
                className="flex-1"
                onClick={() => void handleCreateTag()}
                disabled={!newTagName.trim() || createTagMutation.isPending}
              >
                {createTagMutation.isPending ? t("picker.creating") : t("picker.create")}
              </Button>
              <Button size="sm" variant="outline" onClick={cancelCreating}>
                {t("common:cancel")}
              </Button>
            </div>
          </div>
        ) : (
          <Command shouldFilter={false}>
            <CommandInput
              placeholder={t("picker.searchPlaceholder")}
              value={search}
              onValueChange={setSearch}
            />
            <CommandList>
              {isLoading ? (
                <div className="text-muted-foreground py-6 text-center text-sm">
                  {t("picker.loading")}
                </div>
              ) : (
                <>
                  {canCreateNew && (
                    <CommandGroup>
                      <CommandItem
                        key="create-new"
                        value="create-new"
                        onSelect={startCreating}
                        className="cursor-pointer"
                      >
                        <Plus className="mr-2 h-4 w-4" />
                        {t("picker.createTag", { name: search.trim() })}
                      </CommandItem>
                    </CommandGroup>
                  )}
                  {canCreateNew && filteredTags.length > 0 && <CommandSeparator />}
                  <CommandGroup
                    heading={
                      canCreateNew && filteredTags.length > 0 ? t("picker.existingTags") : undefined
                    }
                  >
                    {filteredTags.length === 0 && !canCreateNew ? (
                      <div className="text-muted-foreground py-6 text-center text-sm">
                        {t("picker.noTagsFound")}
                      </div>
                    ) : (
                      filteredTags.map((tag) => {
                        const isSelected = selectedIds.has(tag.id);
                        return (
                          <CommandItem
                            key={tag.id}
                            value={`tag-${tag.id}`}
                            onSelect={() => toggleTag(tag)}
                            className="cursor-pointer"
                          >
                            <div
                              className={cn(
                                "border-primary mr-2 flex h-4 w-4 items-center justify-center rounded-sm border",
                                isSelected
                                  ? "bg-primary text-primary-foreground"
                                  : "opacity-50 [&_svg]:invisible"
                              )}
                            >
                              <Check className="h-3 w-3" />
                            </div>
                            <span
                              className="mr-2 h-3 w-3 rounded-full"
                              style={{ backgroundColor: tag.color }}
                            />
                            <span className="truncate">{tag.name}</span>
                          </CommandItem>
                        );
                      })
                    )}
                  </CommandGroup>
                </>
              )}
            </CommandList>
          </Command>
        )}
      </PopoverContent>
    </Popover>
  );
}
