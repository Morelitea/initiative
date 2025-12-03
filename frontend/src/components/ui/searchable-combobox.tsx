import { useEffect, useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "./button";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem } from "./command";

export interface SearchableComboboxItem {
  value: string;
  label: string;
}

export interface SearchableComboboxProps {
  items: SearchableComboboxItem[];
  value?: string | null;
  onValueChange?: (value: string) => void;
  placeholder?: string;
  emptyMessage?: string;
  className?: string;
  buttonClassName?: string;
  disabled?: boolean;
}

export const SearchableCombobox = ({
  items,
  value,
  onValueChange,
  placeholder = "Select an option",
  emptyMessage = "No results found.",
  className,
  buttonClassName,
  disabled = false,
}: SearchableComboboxProps) => {
  const [open, setOpen] = useState(false);
  const [internalValue, setInternalValue] = useState(value ?? "");

  useEffect(() => {
    if (value !== undefined && value !== internalValue) {
      setInternalValue(value ?? "");
    }
  }, [value, internalValue]);

  const selectedValue = value ?? internalValue;
  const selectedItem = items.find(
    (item) => item.value.toLowerCase() === selectedValue.toLowerCase()
  );

  const handleSelect = (currentValue: string) => {
    if (disabled) {
      return;
    }
    setInternalValue(currentValue);
    onValueChange?.(currentValue);
    setOpen(false);
  };

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
            className={cn("w-full justify-between", buttonClassName)}
            disabled={disabled}
          >
            {selectedItem?.label ?? placeholder}
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[320px] p-0">
          <Command>
            <CommandInput placeholder="Search..." disabled={disabled} />
            <CommandEmpty>{emptyMessage}</CommandEmpty>
            <CommandGroup className="max-h-64 overflow-y-auto">
              {items.map((item) => (
                <CommandItem
                  key={item.value}
                  value={item.label}
                  onSelect={() => handleSelect(item.value)}
                >
                  <Check
                    className={cn(
                      "mr-2 h-4 w-4",
                      item.value === selectedValue ? "opacity-100" : "opacity-0"
                    )}
                  />
                  {item.label}
                </CommandItem>
              ))}
            </CommandGroup>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
};
