import { Check, ChevronsUpDown, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { cn } from "@/lib/utils";

import { Button } from "./button";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem } from "./command";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";
import type { SearchableComboboxItem } from "./searchable-combobox";

export interface AsyncComboboxProps {
  /** The current page of results. The server has already filtered these. */
  items: SearchableComboboxItem[];
  value?: string | null;
  onValueChange?: (value: string) => void;
  /**
   * Called with the debounced search text, and with "" when the popover
   * opens. Drive the query from this — not from every keystroke.
   */
  onSearchChange: (query: string) => void;
  /** Called when the popover opens/closes — gate the query's `enabled` on it. */
  onOpenChange?: (open: boolean) => void;
  /**
   * Label for the current `value`. Server search only returns matches for the
   * live query, so the selected item is often absent from `items`; the caller
   * remembers its label.
   */
  selectedLabel?: string | null;
  loading?: boolean;
  debounceMs?: number;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyMessage?: string;
  className?: string;
  buttonClassName?: string;
  disabled?: boolean;
  "aria-label"?: string;
}

/**
 * Combobox backed by a server-side typeahead.
 *
 * The sibling ``SearchableCombobox`` filters a list the caller has already
 * fetched in full, which forces a fetch-all for collections that can run to
 * tens of thousands of rows. This variant keeps the request proportional to
 * what the user is looking for: it debounces the query text and hands it back
 * so the caller can fetch a small page, and it does no client-side filtering
 * of its own.
 */
export const AsyncCombobox = ({
  items,
  value,
  onValueChange,
  onSearchChange,
  onOpenChange,
  selectedLabel,
  loading = false,
  debounceMs = 250,
  placeholder,
  searchPlaceholder,
  emptyMessage,
  className,
  buttonClassName,
  disabled = false,
  "aria-label": ariaLabel,
}: AsyncComboboxProps) => {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebouncedValue(query, debounceMs);

  // Held in a ref so an inline (unmemoized) callback prop doesn't re-fire the
  // search on every render of the parent.
  const onSearchChangeRef = useRef(onSearchChange);
  onSearchChangeRef.current = onSearchChange;

  useEffect(() => {
    onSearchChangeRef.current(debouncedQuery);
  }, [debouncedQuery]);

  const handleOpenChange = (nextOpen: boolean) => {
    if (disabled) return;
    setOpen(nextOpen);
    onOpenChange?.(nextOpen);
    if (!nextOpen) {
      setQuery("");
    }
  };

  const handleSelect = (nextValue: string) => {
    if (disabled) return;
    onValueChange?.(nextValue);
    handleOpenChange(false);
  };

  const selectedItem = items.find((item) => item.value === value);
  const triggerLabel = selectedLabel ?? selectedItem?.label ?? placeholder ?? t("selectAnOption");

  return (
    <div className={cn("w-full", className)}>
      <Popover open={disabled ? false : open} onOpenChange={handleOpenChange}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={!disabled && open}
            aria-label={ariaLabel}
            className={cn("w-full justify-between", buttonClassName)}
            disabled={disabled}
          >
            <span className="truncate">{triggerLabel}</span>
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[320px] p-0">
          {/* The server decides what matches; filtering again here would hide
              results that matched on something other than the label. */}
          <Command shouldFilter={false}>
            <CommandInput
              placeholder={searchPlaceholder ?? t("search")}
              value={query}
              onValueChange={setQuery}
            />
            {loading ? (
              <div className="flex items-center justify-center gap-2 py-6 text-muted-foreground text-sm">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t("loading")}
              </div>
            ) : (
              <>
                <CommandEmpty>{emptyMessage ?? t("noResults")}</CommandEmpty>
                <CommandGroup className="max-h-64 overflow-y-auto">
                  {items.map((item) => (
                    <CommandItem
                      key={item.value}
                      value={item.value}
                      onSelect={() => handleSelect(item.value)}
                    >
                      <Check
                        className={cn(
                          "mr-2 h-4 w-4 shrink-0",
                          item.value === value ? "opacity-100" : "opacity-0"
                        )}
                      />
                      <span className="truncate">{item.label}</span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
};
