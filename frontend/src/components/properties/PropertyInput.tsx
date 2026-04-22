import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, ChevronDown, Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { useAppendPropertyOption } from "@/hooks/useProperties";
import { useUsers } from "@/hooks/useUsers";
import { cn } from "@/lib/utils";
import {
  PropertyType,
  type PropertyDefinitionRead,
  type PropertyOption,
  type PropertySummary,
} from "@/api/generated/initiativeAPI.schemas";

type PropertyDefinitionLike = PropertyDefinitionRead | PropertySummary;

export interface PropertyInputProps {
  definition: PropertyDefinitionLike;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled?: boolean;
  className?: string;
}

// ── Type guards / coercion helpers ──────────────────────────────────────────

const coerceString = (value: unknown): string => {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
};

const coerceNumber = (value: unknown): string => {
  if (value == null || value === "") return "";
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? String(parsed) : "";
  }
  return "";
};

const coerceBoolean = (value: unknown): boolean => value === true;

const coerceStringArray = (value: unknown): string[] => {
  if (Array.isArray(value)) {
    return value.filter((v): v is string => typeof v === "string");
  }
  return [];
};

const coerceUserId = (value: unknown): number | null => {
  if (value == null) return null;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "object" && value !== null && "id" in value) {
    const id = (value as { id: unknown }).id;
    if (typeof id === "number" && Number.isFinite(id)) return id;
  }
  return null;
};

// Construct the (minimal) ``PropertyDefinitionRead`` shape the append-option
// hook expects. The local definition may arrive as a ``PropertySummary``
// embedded on an entity read; those have the same ``options`` + id fields
// under different names.
const toDefinitionForPatch = (defn: PropertyDefinitionLike): PropertyDefinitionRead => {
  if ("id" in defn) return defn;
  const summary = defn as PropertySummary;
  return {
    id: summary.property_id,
    // The remaining fields aren't used by the append helper, but the type
    // demands them. They're harmless placeholders.
    guild_id: 0,
    name: summary.name,
    type: summary.type,
    applies_to: summary.applies_to,
    position: 0,
    color: null,
    options: summary.options ?? null,
    created_at: "",
    updated_at: "",
  } as PropertyDefinitionRead;
};

// ── Component ──────────────────────────────────────────────────────────────

export const PropertyInput = ({
  definition,
  value,
  onChange,
  disabled = false,
  className,
}: PropertyInputProps) => {
  const { t } = useTranslation(["properties", "common"]);
  const { data: users = [] } = useUsers({
    enabled: definition.type === PropertyType.user_reference,
  });

  const options = useMemo<PropertyOption[]>(
    () => (definition.options ?? []) as PropertyOption[],
    [definition.options]
  );

  switch (definition.type) {
    case PropertyType.text: {
      return (
        <Input
          type="text"
          value={coerceString(value)}
          onChange={(e) => {
            const next = e.target.value;
            onChange(next === "" ? null : next);
          }}
          placeholder={t("properties:input.textPlaceholder")}
          disabled={disabled}
          className={cn("bg-transparent", className)}
        />
      );
    }

    case PropertyType.number: {
      return (
        <Input
          type="number"
          inputMode="numeric"
          value={coerceNumber(value)}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === "") {
              onChange(null);
              return;
            }
            const parsed = Number(raw);
            onChange(Number.isFinite(parsed) ? parsed : null);
          }}
          placeholder={t("properties:input.numberPlaceholder")}
          disabled={disabled}
          className={cn("bg-transparent", className)}
        />
      );
    }

    case PropertyType.checkbox: {
      return (
        <div className={cn("flex h-9 items-center", className)}>
          <Checkbox
            checked={coerceBoolean(value)}
            onCheckedChange={(checked) => onChange(checked === true)}
            disabled={disabled}
          />
        </div>
      );
    }

    case PropertyType.url: {
      return (
        <Input
          type="url"
          value={coerceString(value)}
          onChange={(e) => {
            const next = e.target.value;
            onChange(next === "" ? null : next);
          }}
          placeholder={t("properties:input.urlPlaceholder")}
          disabled={disabled}
          className={cn("bg-transparent", className)}
        />
      );
    }

    case PropertyType.date: {
      const stored = coerceString(value);
      return (
        <DateTimePicker
          value={stored}
          includeTime={false}
          onChange={(next) => onChange(next === "" ? null : next)}
          disabled={disabled}
          clearLabel={t("properties:input.clear")}
        />
      );
    }

    case PropertyType.datetime: {
      // DateTimePicker stores `yyyy-MM-dd'T'HH:mm` as a local-time string.
      // Convert to a fully-qualified ISO string (with TZ offset) on write so
      // the backend stores an unambiguous instant.
      const stored = coerceString(value);
      const localValue = stored ? localFromIso(stored) : "";
      return (
        <DateTimePicker
          value={localValue}
          includeTime
          onChange={(next) => {
            if (!next) {
              onChange(null);
              return;
            }
            const date = new Date(next);
            if (Number.isNaN(date.getTime())) {
              onChange(null);
              return;
            }
            onChange(date.toISOString());
          }}
          disabled={disabled}
          clearLabel={t("properties:input.clear")}
        />
      );
    }

    case PropertyType.select: {
      return (
        <PropertyOptionPicker
          definition={definition}
          options={options}
          mode="single"
          selected={coerceString(value)}
          onChangeSingle={(next) => onChange(next ?? null)}
          disabled={disabled}
          className={className}
        />
      );
    }

    case PropertyType.multi_select: {
      return (
        <PropertyOptionPicker
          definition={definition}
          options={options}
          mode="multi"
          selectedMulti={coerceStringArray(value)}
          onChangeMulti={(next) => onChange(next)}
          disabled={disabled}
          className={className}
        />
      );
    }

    case PropertyType.user_reference: {
      const currentId = coerceUserId(value);
      const items = users.map((user) => ({
        value: String(user.id),
        label: user.full_name ?? user.email,
      }));
      return (
        <SearchableCombobox
          items={items}
          value={currentId !== null ? String(currentId) : ""}
          onValueChange={(next) => {
            if (!next) {
              onChange(null);
              return;
            }
            const parsed = Number(next);
            onChange(Number.isFinite(parsed) ? parsed : null);
          }}
          placeholder={t("properties:input.userPlaceholder")}
          emptyMessage={t("properties:input.textPlaceholder")}
          disabled={disabled}
          className={className}
        />
      );
    }

    default: {
      // Exhaustiveness check — fall back to a read-only rendering.
      return (
        <span className="text-muted-foreground text-sm">
          {String(value ?? t("properties:input.textPlaceholder"))}
        </span>
      );
    }
  }
};

// ── Inline-creating option picker ───────────────────────────────────────────

type PropertyOptionPickerProps = {
  definition: PropertyDefinitionLike;
  options: PropertyOption[];
  disabled?: boolean;
  className?: string;
} & (
  | {
      mode: "single";
      selected: string;
      onChangeSingle: (next: string | null) => void;
      selectedMulti?: never;
      onChangeMulti?: never;
    }
  | {
      mode: "multi";
      selectedMulti: string[];
      onChangeMulti: (next: string[]) => void;
      selected?: never;
      onChangeSingle?: never;
    }
);

const PropertyOptionPicker = ({
  definition,
  options,
  mode,
  selected,
  onChangeSingle,
  selectedMulti,
  onChangeMulti,
  disabled,
  className,
}: PropertyOptionPickerProps) => {
  const { t } = useTranslation(["properties", "common"]);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const { appendOption, isPending } = useAppendPropertyOption();

  const isMulti = mode === "multi";
  const selectedArr = isMulti ? (selectedMulti ?? []) : selected ? [selected] : [];

  const knownValues = useMemo(() => new Set(options.map((option) => option.value)), [options]);

  const filteredOptions = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return options;
    return options.filter((option) => option.label.toLowerCase().includes(needle));
  }, [options, search]);

  const exactLabelMatch = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return null;
    return options.find((option) => option.label.trim().toLowerCase() === needle) ?? null;
  }, [options, search]);

  const canCreate = search.trim().length > 0 && !exactLabelMatch && !disabled;

  const handleToggle = (value: string) => {
    if (isMulti) {
      const current = selectedMulti ?? [];
      const next = current.includes(value)
        ? current.filter((v) => v !== value)
        : [...current, value];
      onChangeMulti(next);
      return;
    }
    if (selected === value) {
      onChangeSingle(null);
    } else {
      onChangeSingle(value);
      setOpen(false);
    }
  };

  const handleCreate = async () => {
    if (!search.trim()) return;
    try {
      const result = await appendOption(toDefinitionForPatch(definition), search);
      setSearch("");
      const slug = result.option.value;
      if (isMulti) {
        const current = selectedMulti ?? [];
        if (!current.includes(slug)) {
          onChangeMulti([...current, slug]);
        }
      } else {
        onChangeSingle(slug);
        setOpen(false);
      }
    } catch {
      // Toast surfaced by the hook.
    }
  };

  const selectedOptions = selectedArr
    .map(
      (slug) =>
        options.find((option) => option.value === slug) ?? { value: slug, label: slug, color: null }
    )
    .map((option) => ({
      ...option,
      known: knownValues.has(option.value),
    }));

  const placeholder = isMulti
    ? t("properties:input.multiSelectPlaceholder")
    : t("properties:input.selectPlaceholder");

  return (
    <Popover open={open} onOpenChange={(next) => (!disabled ? setOpen(next) : null)}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          disabled={disabled}
          className={cn(
            "h-9 w-full justify-between bg-transparent font-normal",
            selectedOptions.length === 0 && "text-muted-foreground",
            className
          )}
        >
          {selectedOptions.length === 0 ? (
            <span className="truncate">{placeholder}</span>
          ) : (
            <span className="flex min-w-0 flex-1 flex-wrap items-center gap-1 overflow-hidden">
              {selectedOptions.map((option) => (
                <span
                  key={option.value}
                  className={cn(
                    "inline-flex max-w-full items-center gap-1 truncate rounded-sm px-1.5 py-0.5 text-xs",
                    option.known
                      ? "bg-muted text-foreground"
                      : "bg-muted text-muted-foreground italic"
                  )}
                >
                  {option.color ? (
                    <span
                      className="inline-block h-2 w-2 shrink-0 rounded-full"
                      style={{ backgroundColor: option.color }}
                    />
                  ) : null}
                  <span className="truncate">
                    {option.known
                      ? option.label
                      : t("properties:input.unknownOption", { value: option.value })}
                  </span>
                  {isMulti ? (
                    <span
                      role="button"
                      aria-label={t("properties:input.clear")}
                      className="text-muted-foreground hover:text-foreground ml-0.5 shrink-0"
                      onClick={(e) => {
                        e.stopPropagation();
                        onChangeMulti((selectedMulti ?? []).filter((v) => v !== option.value));
                      }}
                    >
                      <X className="h-3 w-3" />
                    </span>
                  ) : null}
                </span>
              ))}
            </span>
          )}
          <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput
            placeholder={t("properties:input.searchOptions")}
            value={search}
            onValueChange={setSearch}
            disabled={isPending}
          />
          <CommandList>
            {filteredOptions.length === 0 && !canCreate ? (
              <CommandEmpty>{t("properties:picker.empty")}</CommandEmpty>
            ) : null}
            {filteredOptions.length > 0 ? (
              <CommandGroup>
                {filteredOptions.map((option) => {
                  const isSelected = selectedArr.includes(option.value);
                  return (
                    <CommandItem
                      key={option.value}
                      value={option.value}
                      onSelect={() => handleToggle(option.value)}
                      className="flex items-center gap-2"
                    >
                      {option.color ? (
                        <span
                          className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                          style={{ backgroundColor: option.color }}
                        />
                      ) : null}
                      <span className="flex-1 truncate">{option.label}</span>
                      {isSelected ? <Check className="h-4 w-4 shrink-0" /> : null}
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            ) : null}
            {canCreate ? (
              <>
                {filteredOptions.length > 0 ? <CommandSeparator /> : null}
                <CommandGroup>
                  <CommandItem
                    value="__create__"
                    onSelect={handleCreate}
                    disabled={isPending}
                    className="flex items-center gap-2"
                  >
                    <Plus className="h-4 w-4 shrink-0" />
                    <span className="truncate">
                      {t("properties:input.createOption", { label: search.trim() })}
                    </span>
                  </CommandItem>
                </CommandGroup>
              </>
            ) : null}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
};

// ── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Convert a stored ISO-8601 timestamp into the local-time `yyyy-MM-dd'T'HH:mm`
 * format the DateTimePicker primitive expects.
 */
const localFromIso = (iso: string): string => {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
};
