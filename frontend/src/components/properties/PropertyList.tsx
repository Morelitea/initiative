import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { PropertySummary, Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  useSetDocumentProperties,
  useSetEventProperties,
  useSetTaskProperties,
} from "@/hooks/useProperties";
import { cn } from "@/lib/utils";

import { PropertyFields } from "./PropertyFields";
import { normalizePropertyValue } from "./propertyHelpers";

export type PropertyEntityKind = "document" | "task" | "event";

export interface PropertyListProps {
  entityKind: PropertyEntityKind;
  entityId: number;
  properties: PropertySummary[];
  disabled?: boolean;
  className?: string;
  /** Initiative that scopes any `user_reference` picker in the list. */
  initiativeId?: number | null;
  /** See `PropertyInput`'s `canOpen`. */
  canOpen?: { tool: Tool; id: number | null | undefined };
}

const SAVE_DEBOUNCE_MS = 400;

// Internal draft map keeps optimistic local values keyed by property_id.
type DraftMap = Record<number, unknown>;

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
    const current = normalizePropertyValue(property);
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
  initiativeId,
  canOpen,
}: PropertyListProps) => {
  const { t } = useTranslation("properties");

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
      initial[property.property_id] = normalizePropertyValue(property);
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
          next[property.property_id] = normalizePropertyValue(property);
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
      const options = { onSettled: () => pendingRef.current.clear() };
      if (entityKind === "document") {
        setDocumentMutation.mutate({ documentId: entityId, ...variables }, options);
      } else if (entityKind === "event") {
        setEventMutation.mutate({ eventId: entityId, ...variables }, options);
      } else {
        setTaskMutation.mutate({ taskId: entityId, ...variables }, options);
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

  const attached = useMemo(
    () => properties.filter((p) => !removedIds.has(p.property_id)),
    [properties, removedIds]
  );

  return (
    <div className={cn("space-y-2", className)}>
      <PropertyFields
        properties={attached}
        values={drafts}
        onChange={handleChange}
        onRemove={handleRemove}
        disabled={disabled}
        initiativeId={initiativeId}
        canOpen={canOpen}
      />
      {activeMutation.isPending ? (
        <p className="text-muted-foreground text-xs">{t("saving")}</p>
      ) : null}
    </div>
  );
};
