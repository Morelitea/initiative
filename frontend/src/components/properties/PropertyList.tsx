import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import {
  useSetDocumentProperties,
  useSetEventProperties,
  useSetTaskProperties,
} from "@/hooks/useProperties";
import { PropertyType, type PropertySummary } from "@/api/generated/initiativeAPI.schemas";

import { PropertyInput } from "./PropertyInput";
import { iconForPropertyType } from "./propertyTypeIcons";

export type PropertyEntityKind = "document" | "task" | "event";

export interface PropertyListProps {
  entityKind: PropertyEntityKind;
  entityId: number;
  properties: PropertySummary[];
  disabled?: boolean;
  className?: string;
}

const SAVE_DEBOUNCE_MS = 400;

// Internal draft map keeps optimistic local values keyed by property_id.
type DraftMap = Record<number, unknown>;

/**
 * Convert the server-side `PropertySummary.value` into the shape the input
 * component expects locally.
 *
 * - user_reference: the server returns `{id, full_name}` on reads; we keep
 *   the id in our draft so we can round-trip it through the outgoing payload.
 * - everything else: passes through unchanged.
 */
const normalizeIncomingValue = (property: PropertySummary): unknown => {
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

/**
 * Build the replace-all payload for the PUT /properties endpoints from the
 * current draft state. Every property in ``properties`` is sent even when
 * its value is empty — the backend persists attached-but-empty rows so
 * adding a property without setting a value still survives a refresh.
 * Properties present in ``removedIds`` are dropped from the payload so
 * that clicking the row's remove button detaches the property entirely
 * (as opposed to just clearing its value).
 */
const buildPayload = (drafts: DraftMap, properties: PropertySummary[], removedIds: Set<number>) => {
  const byId = new Map(properties.map((p) => [p.property_id, p] as const));
  const values: Array<{ property_id: number; value: unknown }> = [];
  const seen = new Set<number>();
  for (const [idStr, draft] of Object.entries(drafts)) {
    const id = Number(idStr);
    if (!Number.isFinite(id) || !byId.has(id)) continue;
    if (removedIds.has(id)) continue;
    seen.add(id);
    values.push({ property_id: id, value: draft ?? null });
  }
  // Include any incoming properties the user hasn't touched; they must stay
  // attached since PUT has replace-all semantics.
  for (const property of properties) {
    if (seen.has(property.property_id)) continue;
    if (removedIds.has(property.property_id)) continue;
    const current = normalizeIncomingValue(property);
    values.push({ property_id: property.property_id, value: current ?? null });
  }
  return values;
};

export const PropertyList = ({
  entityKind,
  entityId,
  properties,
  disabled = false,
  className,
}: PropertyListProps) => {
  const { t } = useTranslation(["properties", "common"]);

  const setDocumentMutation = useSetDocumentProperties();
  const setTaskMutation = useSetTaskProperties();
  const setEventMutation = useSetEventProperties();
  const activeMutation =
    entityKind === "document"
      ? setDocumentMutation
      : entityKind === "event"
        ? setEventMutation
        : setTaskMutation;

  // Seed drafts from incoming properties. When the server returns a new
  // snapshot, reconcile any property whose id we don't have a local pending
  // draft for, leaving in-flight drafts untouched.
  const [drafts, setDrafts] = useState<DraftMap>(() => {
    const initial: DraftMap = {};
    for (const property of properties) {
      initial[property.property_id] = normalizeIncomingValue(property);
    }
    return initial;
  });

  const pendingRef = useRef<Set<number>>(new Set());
  // Property ids the user has removed locally but whose server snapshot may
  // not yet reflect the removal. ``buildPayload`` drops these from the PUT.
  const [removedIds, setRemovedIds] = useState<Set<number>>(() => new Set());

  useEffect(() => {
    setDrafts((prev) => {
      const next: DraftMap = { ...prev };
      const incomingIds = new Set<number>();
      for (const property of properties) {
        incomingIds.add(property.property_id);
        // Only overwrite if the user hasn't actively edited this field.
        if (!pendingRef.current.has(property.property_id)) {
          next[property.property_id] = normalizeIncomingValue(property);
        }
      }
      // Drop drafts for properties no longer on the entity.
      for (const key of Object.keys(next)) {
        const id = Number(key);
        if (!incomingIds.has(id)) delete next[id];
      }
      return next;
    });
    // Drop removal markers once the server confirms the property is gone.
    setRemovedIds((prev) => {
      if (prev.size === 0) return prev;
      const stillAttached = new Set(properties.map((p) => p.property_id));
      const next = new Set<number>();
      for (const id of prev) {
        if (stillAttached.has(id)) next.add(id);
      }
      return next.size === prev.size ? prev : next;
    });
  }, [properties]);

  // Debounced save: a single timer coalesces all recent edits into one PUT.
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestDraftsRef = useRef<DraftMap>(drafts);
  latestDraftsRef.current = drafts;

  const latestRemovedRef = useRef<Set<number>>(removedIds);
  latestRemovedRef.current = removedIds;

  const scheduleSave = useCallback(() => {
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
    }
    saveTimeoutRef.current = setTimeout(() => {
      saveTimeoutRef.current = null;
      const payload = buildPayload(latestDraftsRef.current, properties, latestRemovedRef.current);
      const variables = { values: { values: payload } };
      if (entityKind === "document") {
        setDocumentMutation.mutate(
          { documentId: entityId, ...variables },
          {
            onSettled: () => {
              pendingRef.current.clear();
            },
          }
        );
      } else if (entityKind === "event") {
        setEventMutation.mutate(
          { eventId: entityId, ...variables },
          {
            onSettled: () => {
              pendingRef.current.clear();
            },
          }
        );
      } else {
        setTaskMutation.mutate(
          { taskId: entityId, ...variables },
          {
            onSettled: () => {
              pendingRef.current.clear();
            },
          }
        );
      }
    }, SAVE_DEBOUNCE_MS);
  }, [entityKind, entityId, properties, setDocumentMutation, setTaskMutation, setEventMutation]);

  useEffect(
    () => () => {
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    },
    []
  );

  const handleChange = useCallback(
    (propertyId: number, value: unknown) => {
      pendingRef.current.add(propertyId);
      setDrafts((prev) => ({ ...prev, [propertyId]: value }));
      scheduleSave();
    },
    [scheduleSave]
  );

  const handleRemove = useCallback(
    (propertyId: number) => {
      pendingRef.current.add(propertyId);
      setRemovedIds((prev) => {
        if (prev.has(propertyId)) return prev;
        const next = new Set(prev);
        next.add(propertyId);
        return next;
      });
      scheduleSave();
    },
    [scheduleSave]
  );

  const sorted = useMemo(
    () =>
      [...properties]
        .filter((p) => !removedIds.has(p.property_id))
        .sort((a, b) => a.name.localeCompare(b.name)),
    [properties, removedIds]
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
          const inputId = `property-${entityKind}-${entityId}-${property.property_id}`;
          const draft = drafts[property.property_id];
          const Icon = iconForPropertyType(property.type);
          return (
            <li
              key={property.property_id}
              className="grid grid-cols-[minmax(0,8rem)_1fr_auto] items-center gap-2"
            >
              <Label
                htmlFor={inputId}
                className="text-muted-foreground flex min-w-0 items-center gap-1.5 text-xs font-normal"
                title={property.name}
              >
                <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span className="truncate">{property.name}</span>
              </Label>
              <div id={inputId} className="min-w-0">
                <PropertyInput
                  definition={property}
                  value={draft}
                  onChange={(next) => handleChange(property.property_id, next)}
                  disabled={disabled}
                />
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                className="text-muted-foreground"
                onClick={() => handleRemove(property.property_id)}
                disabled={disabled}
                aria-label={t("properties:remove")}
              >
                <X className="h-4 w-4" />
              </Button>
            </li>
          );
        })}
      </ul>
      {activeMutation.isPending ? (
        <p className="text-muted-foreground text-xs">{t("properties:saving")}</p>
      ) : null}
    </div>
  );
};
