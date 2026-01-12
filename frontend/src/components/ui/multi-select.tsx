import { useMemo } from "react";
import { Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export interface MultiSelectOption {
  value: string;
  label: string;
}

interface MultiSelectProps {
  selectedValues: string[];
  options: MultiSelectOption[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  emptyMessage?: string;
  disabled?: boolean;
  className?: string;
}

export const MultiSelect = ({
  selectedValues,
  options,
  onChange,
  placeholder = "Select...",
  emptyMessage = "No options available",
  disabled = false,
  className,
}: MultiSelectProps) => {
  const toggleValue = (value: string) => {
    if (selectedValues.includes(value)) {
      onChange(selectedValues.filter((v) => v !== value));
    } else {
      onChange([...selectedValues, value]);
    }
  };

  const selectAll = () => {
    onChange(options.map((option) => option.value));
  };

  const clearAll = () => {
    onChange([]);
  };

  const displayValue = useMemo(() => {
    if (selectedValues.length === 0) {
      return placeholder;
    }
    if (selectedValues.length === options.length) {
      return "All selected";
    }
    if (selectedValues.length === 1) {
      const option = options.find((o) => o.value === selectedValues[0]);
      return option?.label ?? placeholder;
    }
    return `${selectedValues.length} selected`;
  }, [selectedValues, options, placeholder]);

  if (options.length === 0) {
    return <p className="text-muted-foreground text-sm">{emptyMessage}</p>;
  }

  return (
    <Select value="__multiselect__" disabled={disabled}>
      <SelectTrigger className={className}>
        <SelectValue>
          <span className={selectedValues.length === 0 ? "text-muted-foreground" : ""}>
            {displayValue}
          </span>
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        <div
          className="border-border flex flex-col gap-0.5 border-b pb-1"
          onClick={(e) => e.stopPropagation()}
        >
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={selectAll}
            disabled={selectedValues.length === options.length}
            className="h-8 w-full justify-start px-2 font-normal"
          >
            Select all
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={clearAll}
            disabled={selectedValues.length === 0}
            className="h-8 w-full justify-start px-2 font-normal"
          >
            Clear all
          </Button>
        </div>
        {options.map((option) => {
          const isSelected = selectedValues.includes(option.value);
          return (
            <SelectItem
              key={option.value}
              value={option.value}
              onPointerUp={(e) => {
                e.preventDefault();
                toggleValue(option.value);
              }}
              onPointerDown={(e) => {
                e.preventDefault();
              }}
            >
              <div className="flex w-full items-center gap-2">
                <div className="flex h-4 w-4 items-center justify-center">
                  {isSelected ? <Check className="h-4 w-4" /> : null}
                </div>
                <span>{option.label}</span>
              </div>
            </SelectItem>
          );
        })}
      </SelectContent>
    </Select>
  );
};
