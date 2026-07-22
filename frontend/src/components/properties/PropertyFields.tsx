import { X } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  type PropertyDefinitionRead,
  type PropertySummary,
  PropertyType,
} from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

import { PropertyInput } from "./PropertyInput";
import { iconForPropertyType } from "./propertyTypeIcons";

export interface PropertyFieldsProps {
  /** Attached property rows — real server rows or locally-added stubs. */
  properties: PropertySummary[];
  /** Current value keyed by ``property_id``. Fully controlled by the parent. */
  values: Record<number, unknown>;
  onChange: (propertyId: number, value: unknown) => void;
  onRemove: (propertyId: number) => void;
  disabled?: boolean;
  /** Initiative that scopes any ``user_reference`` picker in the list. */
  initiativeId?: number | null;
  className?: string;
}

/** Build a stub ``PropertySummary`` from a definition the user just picked but
 *  hasn't given a value yet, so it can render alongside real attached rows. */
export const propertyStubFromDefinition = (
  definition: PropertyDefinitionRead
): PropertySummary => ({
  property_id: definition.id,
  name: definition.name,
  type: definition.type,
  options: definition.options ?? null,
  value: null,
});

/** Convert a server ``PropertySummary.value`` into the shape the controlled
 *  ``values`` map expects: ``user_reference`` collapses to its numeric id
 *  (``PropertyInput`` round-trips the id), everything else passes through. */
export const normalizePropertyValue = (property: PropertySummary): unknown => {
  if (property.type === PropertyType.user_reference) {
    if (
      property.value &&
      typeof property.value === "object" &&
      "id" in property.value &&
      typeof (property.value as { id: unknown }).id === "number"
    ) {
      return (property.value as { id: number }).id;
    }
    return null;
  }
  return property.value ?? null;
};

/** Pull the ``{id, full_name}`` a ``user_reference`` value carries so the
 *  picker can render the selected name without a search round-trip. */
const userReferenceValue = (
  property: PropertySummary
): { id: number; full_name?: string | null } | null => {
  if (property.type !== PropertyType.user_reference) return null;
  const raw = property.value;
  if (
    raw &&
    typeof raw === "object" &&
    "id" in raw &&
    typeof (raw as { id: unknown }).id === "number"
  ) {
    return raw as { id: number; full_name?: string | null };
  }
  return null;
};

/**
 * Presentational, fully-controlled list of custom property inputs. It owns no
 * persistence, debounce, or draft state — the parent holds the values and
 * decides when/how to save (immediate PUT vs batch into a create/update
 * request). ``PropertyList`` wraps this for the autosaving document/event flow.
 */
export const PropertyFields = ({
  properties,
  values,
  onChange,
  onRemove,
  disabled = false,
  initiativeId,
  className,
}: PropertyFieldsProps) => {
  const { t } = useTranslation(["properties", "common"]);

  const sorted = useMemo(
    () => [...properties].sort((a, b) => a.name.localeCompare(b.name)),
    [properties]
  );

  if (sorted.length === 0) {
    return (
      <p className={cn("text-muted-foreground text-sm", className)}>
        {t("properties:noProperties")}
      </p>
    );
  }

  return (
    <div className={cn("space-y-2", className)}>
      <ul className="space-y-2">
        {sorted.map((property) => {
          const inputId = `property-field-${property.property_id}`;
          const Icon = iconForPropertyType(property.type);
          return (
            <li
              key={property.property_id}
              className="grid grid-cols-[minmax(0,8rem)_1fr_auto] items-center gap-2"
            >
              <Label
                htmlFor={inputId}
                className="flex min-w-0 items-center gap-1.5 font-normal text-muted-foreground text-xs"
                title={property.name}
              >
                <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span className="truncate">{property.name}</span>
              </Label>
              <div id={inputId} className="min-w-0">
                <PropertyInput
                  definition={property}
                  value={values[property.property_id]}
                  onChange={(next) => onChange(property.property_id, next)}
                  disabled={disabled}
                  initiativeId={initiativeId}
                  selectedUser={userReferenceValue(property)}
                />
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                className="text-muted-foreground"
                onClick={() => onRemove(property.property_id)}
                disabled={disabled}
                aria-label={t("properties:remove")}
              >
                <X className="h-4 w-4" />
              </Button>
            </li>
          );
        })}
      </ul>
    </div>
  );
};
