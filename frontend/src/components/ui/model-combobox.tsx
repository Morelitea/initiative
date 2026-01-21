import { useEffect, useRef, useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "./button";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "./command";

export interface ModelComboboxProps {
  models: string[];
  value?: string;
  onValueChange?: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
}

export const ModelCombobox = ({
  models,
  value = "",
  onValueChange,
  placeholder = "Select or type a model",
  disabled = false,
  className,
}: ModelComboboxProps) => {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Filter models based on search
  const filteredModels = models.filter((model) =>
    model.toLowerCase().includes(search.toLowerCase())
  );

  // Check if search matches an existing model exactly
  const exactMatch = models.some((model) => model.toLowerCase() === search.toLowerCase());

  // Show "Use custom" option if search doesn't match any model exactly
  const showCustomOption = search.length > 0 && !exactMatch;

  const handleSelect = (selectedValue: string) => {
    onValueChange?.(selectedValue);
    setSearch("");
    setOpen(false);
  };

  const handleCustomSelect = () => {
    onValueChange?.(search);
    setSearch("");
    setOpen(false);
  };

  // Reset search when popover closes
  useEffect(() => {
    if (!open) {
      setSearch("");
    }
  }, [open]);

  return (
    <div className={cn("w-full", className)}>
      <Popover
        open={disabled ? false : open}
        onOpenChange={(nextOpen) => !disabled && setOpen(nextOpen)}
      >
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={!disabled && open}
            className={cn("w-full justify-between font-normal", !value && "text-muted-foreground")}
            disabled={disabled}
          >
            <span className="truncate">{value || placeholder}</span>
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
          <Command shouldFilter={false}>
            <CommandInput
              ref={inputRef}
              placeholder="Search or type model name..."
              value={search}
              onValueChange={setSearch}
              disabled={disabled}
            />
            <CommandList>
              <CommandEmpty>
                {search.length > 0 ? (
                  <button
                    type="button"
                    className="hover:bg-accent w-full cursor-pointer px-2 py-1.5 text-left text-sm"
                    onClick={handleCustomSelect}
                  >
                    Use &ldquo;{search}&rdquo;
                  </button>
                ) : (
                  "No models available"
                )}
              </CommandEmpty>
              <CommandGroup className="max-h-64 overflow-y-auto">
                {showCustomOption && (
                  <CommandItem
                    value={`__custom__${search}`}
                    onSelect={handleCustomSelect}
                    className="text-muted-foreground"
                  >
                    <Check className="mr-2 h-4 w-4 opacity-0" />
                    Use &ldquo;{search}&rdquo;
                  </CommandItem>
                )}
                {filteredModels.map((model) => (
                  <CommandItem key={model} value={model} onSelect={() => handleSelect(model)}>
                    <Check
                      className={cn("mr-2 h-4 w-4", value === model ? "opacity-100" : "opacity-0")}
                    />
                    {model}
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
