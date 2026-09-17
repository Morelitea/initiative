/**
 * A field that suggests but does not insist.
 *
 * For a value where something else knows most of the likely answers and the
 * list is not the whole truth: the models a connection offers, the claims a
 * provider says it carries. Typing something that is not on the list is a
 * first-class answer, not an escape hatch, so whatever is typed is offered
 * back as itself.
 *
 * Suggestions can arrive late — `onOpen` fires when the list is first shown,
 * which is when a caller that has to go and ask should go and ask.
 *
 * Every string is the caller's. What is being suggested differs enough between
 * call sites that generic wording would read as nothing in particular, and the
 * words belong in a translated namespace either way.
 */

import { Check, ChevronsUpDown, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import { Button } from "./button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "./command";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";

export interface SuggestComboboxProps {
  /** What is known. May be empty, and may arrive after `onOpen`. */
  suggestions: string[];
  value?: string;
  onValueChange?: (value: string) => void;
  /** The closed field, with nothing chosen. */
  placeholder?: string;
  /** The search box. */
  searchPlaceholder: string;
  /** Shown while `isLoading`. */
  loadingLabel: string;
  /** Shown when there is nothing to suggest. */
  emptyLabel: string;
  /** Offers what was typed, e.g. `Use "{{value}}"`. Not named for `use`:
   *  that prefix reads as a hook to the linter, and it is a label. */
  typedLabel: (typed: string) => string;
  disabled?: boolean;
  className?: string;
  /** Called when the list is first opened — fetch the suggestions here. */
  onOpen?: () => void;
  isLoading?: boolean;
  "aria-label"?: string;
}

export const SuggestCombobox = ({
  suggestions,
  value = "",
  onValueChange,
  placeholder,
  searchPlaceholder,
  loadingLabel,
  emptyLabel,
  typedLabel,
  disabled = false,
  className,
  onOpen,
  isLoading = false,
  "aria-label": ariaLabel,
}: SuggestComboboxProps) => {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const matching = suggestions.filter((item) => item.toLowerCase().includes(search.toLowerCase()));
  const typedIsOnTheList = suggestions.some((item) => item.toLowerCase() === search.toLowerCase());
  const offerTyped = search.length > 0 && !typedIsOnTheList;

  const choose = (chosen: string) => {
    onValueChange?.(chosen);
    setSearch("");
    setOpen(false);
  };

  useEffect(() => {
    if (!open) setSearch("");
  }, [open]);

  const handleOpenChange = (nextOpen: boolean) => {
    if (disabled) return;
    setOpen(nextOpen);
    if (nextOpen) onOpen?.();
  };

  return (
    <div className={cn("w-full", className)}>
      <Popover open={disabled ? false : open} onOpenChange={handleOpenChange}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={!disabled && open}
            aria-label={ariaLabel}
            className={cn("w-full justify-between font-normal", !value && "text-muted-foreground")}
            disabled={disabled}
          >
            <span className="truncate">{value || placeholder}</span>
            <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-(--radix-popover-trigger-width) p-0" align="start">
          <Command shouldFilter={false}>
            <CommandInput
              ref={inputRef}
              placeholder={searchPlaceholder}
              value={search}
              onValueChange={setSearch}
              disabled={disabled}
            />
            <CommandList>
              <CommandEmpty>
                {isLoading ? (
                  <div className="flex items-center justify-center gap-2 py-2 text-muted-foreground text-sm">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {loadingLabel}
                  </div>
                ) : (
                  emptyLabel
                )}
              </CommandEmpty>
              <CommandGroup className="max-h-64 overflow-y-auto">
                {offerTyped && matching.length === 0 && (
                  <CommandItem
                    value={`__typed__${search}`}
                    onSelect={() => choose(search)}
                    className="text-muted-foreground"
                  >
                    <Check className="mr-2 h-4 w-4 opacity-0" />
                    {typedLabel(search)}
                  </CommandItem>
                )}
                {matching.map((item) => (
                  <CommandItem key={item} value={item} onSelect={() => choose(item)}>
                    <Check
                      className={cn("mr-2 h-4 w-4", value === item ? "opacity-100" : "opacity-0")}
                    />
                    {item}
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
};
