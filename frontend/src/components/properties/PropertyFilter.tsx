import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { useProperties } from "@/hooks/useProperties";
import {
  PropertyAppliesTo,
  PropertyType,
  type PropertyDefinitionRead,
} from "@/api/generated/initiativeAPI.schemas";

import { PropertyInput } from "./PropertyInput";
import { iconForPropertyType } from "./propertyTypeIcons";

export type PropertyFilterEntityKind = "document" | "task";

export interface PropertyFilterCondition {
  property_id: number;
  op: string;
  value: unknown;
}

export interface PropertyFilterProps {
  value: PropertyFilterCondition[];
  onChange: (next: PropertyFilterCondition[]) => void;
  appliesTo: PropertyFilterEntityKind;
  maxFilters?: number;
  className?: string;
}

/**
 * Supported filter operators, keyed by the backend :class:`FilterOp` enum.
 *
 * Backend reference: `backend/app/schemas/query.py` ``FilterOp``. We ship a
 * small subset tailored to each property type. ``ilike`` is labeled
 * "contains" in the UI because the backend wraps the value in ``%value%``.
 * ``multi_select`` always uses JSONB containment regardless of ``op``; we
 * keep ``eq`` in the dropdown as a single sensible default for that type.
 */
const BACKEND_OPS = ["eq", "lt", "lte", "gt", "gte", "in_", "ilike", "is_null"] as const;
type BackendOp = (typeof BACKEND_OPS)[number];

const DEFAULT_MAX_FILTERS = 5;

/**
 * Return the ordered list of operators that make sense for a property type.
 * The first entry is used as the default when adding a new filter.
 */
export const opsForType = (type: PropertyType): BackendOp[] => {
  switch (type) {
    case PropertyType.text:
    case PropertyType.url:
      return ["ilike", "eq", "is_null"];
    case PropertyType.number:
    case PropertyType.date:
    case PropertyType.datetime:
      return ["eq", "lt", "lte", "gt", "gte", "is_null"];
    case PropertyType.checkbox:
      return ["eq", "is_null"];
    case PropertyType.select:
      return ["eq", "in_", "is_null"];
    case PropertyType.multi_select:
      // Backend always uses JSONB ``@>`` for multi_select; we only need one row.
      return ["eq"];
    case PropertyType.user_reference:
      return ["eq", "in_", "is_null"];
    default:
      return ["eq"];
  }
};

const isBackendOp = (op: string): op is BackendOp =>
  (BACKEND_OPS as readonly string[]).includes(op);

/**
 * Translate a ``FilterOp`` to its short UI label. Keys are intentionally
 * flat (no nested object per type) so localizers only touch one map.
 */
const useOpLabel = () => {
  const { t } = useTranslation("properties");
  return useCallback((op: string) => t(`filter.ops.${op}` as never, { defaultValue: op }), [t]);
};

/**
 * Produce a sensible default value for a fresh row so the input component
 * renders in a defined state. The backend treats "empty" conditions as
 * no-ops, so we don't need to coerce here — the user just edits the value.
 */
const defaultValueForDefinition = (definition: PropertyDefinitionRead, op: BackendOp): unknown => {
  if (op === "is_null") {
    return true;
  }
  switch (definition.type) {
    case PropertyType.checkbox:
      return false;
    case PropertyType.multi_select:
      return [];
    case PropertyType.number:
      return null;
    default:
      return op === "in_" ? [] : null;
  }
};

export const PropertyFilter = ({
  value,
  onChange,
  appliesTo,
  maxFilters = DEFAULT_MAX_FILTERS,
  className,
}: PropertyFilterProps) => {
  const { t } = useTranslation("properties");
  const opLabel = useOpLabel();

  // Only pull definitions that can attach to this entity kind (incl. "both").
  // The hook caches cross-page so we don't incur a request per component.
  const definitionsQuery = useProperties();

  const eligibleDefinitions = useMemo(() => {
    const all = definitionsQuery.data ?? [];
    return all.filter((definition) => {
      const scope = definition.applies_to;
      return scope === appliesTo || scope === PropertyAppliesTo.both;
    });
  }, [definitionsQuery.data, appliesTo]);

  const definitionsById = useMemo(() => {
    const map = new Map<number, PropertyDefinitionRead>();
    for (const definition of eligibleDefinitions) {
      map.set(definition.id, definition);
    }
    return map;
  }, [eligibleDefinitions]);

  const usedPropertyIds = useMemo(() => new Set(value.map((entry) => entry.property_id)), [value]);

  const handleAddFilter = useCallback(() => {
    const firstAvailable = eligibleDefinitions.find(
      (definition) => !usedPropertyIds.has(definition.id)
    );
    if (!firstAvailable) return;
    const op = opsForType(firstAvailable.type)[0] ?? "eq";
    onChange([
      ...value,
      {
        property_id: firstAvailable.id,
        op,
        value: defaultValueForDefinition(firstAvailable, op),
      },
    ]);
  }, [eligibleDefinitions, usedPropertyIds, value, onChange]);

  const handleRemoveFilter = useCallback(
    (index: number) => {
      onChange(value.filter((_, i) => i !== index));
    },
    [value, onChange]
  );

  const handlePropertyChange = useCallback(
    (index: number, nextPropertyId: number) => {
      const nextDefinition = definitionsById.get(nextPropertyId);
      if (!nextDefinition) return;
      const op = opsForType(nextDefinition.type)[0] ?? "eq";
      onChange(
        value.map((entry, i) =>
          i === index
            ? {
                property_id: nextDefinition.id,
                op,
                value: defaultValueForDefinition(nextDefinition, op),
              }
            : entry
        )
      );
    },
    [definitionsById, value, onChange]
  );

  const handleOpChange = useCallback(
    (index: number, nextOp: string) => {
      const entry = value[index];
      if (!entry) return;
      const definition = definitionsById.get(entry.property_id);
      if (!definition) return;
      const normalized = isBackendOp(nextOp) ? nextOp : "eq";
      // Reset value shape when switching between scalar / array / null ops so
      // the input component isn't stuck with a non-matching draft.
      const shouldResetValue =
        normalized === "in_" ||
        normalized === "is_null" ||
        entry.op === "in_" ||
        entry.op === "is_null";
      const nextValue = shouldResetValue
        ? defaultValueForDefinition(definition, normalized)
        : entry.value;
      onChange(
        value.map((existing, i) =>
          i === index ? { ...existing, op: normalized, value: nextValue } : existing
        )
      );
    },
    [value, onChange, definitionsById]
  );

  const handleValueChange = useCallback(
    (index: number, nextValue: unknown) => {
      onChange(value.map((entry, i) => (i === index ? { ...entry, value: nextValue } : entry)));
    },
    [value, onChange]
  );

  const canAddMore = value.length < maxFilters && eligibleDefinitions.length > usedPropertyIds.size;

  if (eligibleDefinitions.length === 0 && value.length === 0) {
    // Nothing to filter on — don't take up UI real estate.
    return null;
  }

  return (
    <div className={cn("space-y-2", className)}>
      {value.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {value.map((entry, index) => {
            const definition = definitionsById.get(entry.property_id);
            const ops = definition ? opsForType(definition.type) : ["eq"];
            return (
              <li
                key={`${entry.property_id}-${index}`}
                className="flex flex-wrap items-center gap-2 sm:flex-nowrap"
              >
                <div className="min-w-0 flex-1 sm:w-40 sm:flex-none">
                  <Select
                    value={String(entry.property_id)}
                    onValueChange={(next) => handlePropertyChange(index, Number(next))}
                  >
                    <SelectTrigger className="h-9 w-full" aria-label={t("filter.property")}>
                      {definition ? (
                        (() => {
                          const Icon = iconForPropertyType(definition.type);
                          return (
                            <div className="flex min-w-0 items-center gap-2">
                              <Icon className="h-4 w-4 shrink-0" />
                              <span className="truncate">{definition.name}</span>
                            </div>
                          );
                        })()
                      ) : (
                        <SelectValue />
                      )}
                    </SelectTrigger>
                    <SelectContent>
                      {eligibleDefinitions.map((option) => {
                        const Icon = iconForPropertyType(option.type);
                        return (
                          <SelectItem
                            key={option.id}
                            value={String(option.id)}
                            textValue={option.name}
                            disabled={
                              option.id !== entry.property_id && usedPropertyIds.has(option.id)
                            }
                          >
                            <div className="flex items-center gap-2">
                              <Icon className="h-4 w-4 shrink-0" />
                              <span>{option.name}</span>
                            </div>
                          </SelectItem>
                        );
                      })}
                    </SelectContent>
                  </Select>
                </div>
                <div className="sm:w-32">
                  <Select
                    value={entry.op}
                    onValueChange={(next) => handleOpChange(index, next)}
                    disabled={!definition}
                  >
                    <SelectTrigger className="h-9 w-full" aria-label={t("filter.operator")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ops.map((opOption) => (
                        <SelectItem key={opOption} value={opOption}>
                          {opLabel(opOption)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="min-w-0 flex-1">
                  {definition && entry.op !== "is_null" ? (
                    <PropertyInput
                      definition={definition}
                      value={entry.value}
                      onChange={(next) => handleValueChange(index, next)}
                    />
                  ) : (
                    <div className="text-muted-foreground text-sm">{opLabel(entry.op)}</div>
                  )}
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => handleRemoveFilter(index)}
                  aria-label={t("filter.remove")}
                >
                  <X className="h-4 w-4" />
                </Button>
              </li>
            );
          })}
        </ul>
      ) : null}
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={handleAddFilter}
        disabled={!canAddMore}
        className="h-8"
      >
        <Plus className="mr-1 h-4 w-4" />
        {t("filter.addFilter")}
      </Button>
    </div>
  );
};
