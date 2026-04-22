import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Checkbox } from "@/components/ui/checkbox";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { Input } from "@/components/ui/input";
import { MultiSelect } from "@/components/ui/multi-select";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
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
      const current = coerceString(value);
      const knownValues = new Set(options.map((option) => option.value));
      const hasUnknownValue = current !== "" && !knownValues.has(current);
      const selectedOption = options.find((option) => option.value === current);

      // Render the trigger content ourselves rather than passing children to
      // SelectValue. Radix clones SelectValue children into a hidden span in
      // the trigger, which races with portal teardown on selection and throws
      // "Failed to execute 'removeChild' on 'Node'". Reading `current` from our
      // controlled state and rendering inline side-steps the clone entirely.
      return (
        <Select
          value={current === "" ? undefined : current}
          onValueChange={(next) => onChange(next === "" ? null : next)}
          disabled={disabled}
        >
          <SelectTrigger className={cn("bg-transparent", className)}>
            {current === "" ? (
              <span className="text-muted-foreground">
                {t("properties:input.selectPlaceholder")}
              </span>
            ) : hasUnknownValue ? (
              <span className="text-muted-foreground italic">
                {t("properties:input.unknownOption", { value: current })}
              </span>
            ) : selectedOption ? (
              <div className="flex min-w-0 items-center gap-2">
                {selectedOption.color ? (
                  <span
                    className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: selectedOption.color }}
                  />
                ) : null}
                <span className="truncate">{selectedOption.label}</span>
              </div>
            ) : null}
          </SelectTrigger>
          <SelectContent>
            {options.map((option) => (
              <SelectItem key={option.value} value={option.value} textValue={option.label}>
                <div className="flex items-center gap-2">
                  {option.color ? (
                    <span
                      className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                      style={{ backgroundColor: option.color }}
                    />
                  ) : null}
                  <span>{option.label}</span>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      );
    }

    case PropertyType.multi_select: {
      const current = coerceStringArray(value);
      const multiOptions = options.map((option) => ({
        value: option.value,
        label: option.label,
      }));
      return (
        <MultiSelect
          selectedValues={current}
          options={multiOptions}
          onChange={(next) => onChange(next)}
          placeholder={t("properties:input.multiSelectPlaceholder")}
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
