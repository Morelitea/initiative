import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  PropertyDefinitionRead,
  PropertySummary,
  PropertyTarget,
} from "@/api/generated/initiativeAPI.schemas";
import { useSetProperties } from "@/hooks/useProperties";

import { propertyStubFromDefinition } from "./PropertyFields";
import { normalizePropertyValue } from "./propertyHelpers";

/**
 * A row's saved properties plus the ones just added to it, for a
 * `PropertyList` beside an `AddPropertyButton`.
 *
 * An added property shows at once with no value, and is saved straight away
 * so it stays attached across a refresh before anyone fills it in. It drops
 * out of the pending set once the server's copy of the row carries it.
 */
export const usePendingProperties = (
  target: PropertyTarget,
  id: number,
  saved: PropertySummary[]
) => {
  const [pending, setPending] = useState<PropertyDefinitionRead[]>([]);
  // The same list, readable by a second add before the first has rendered.
  const pendingRef = useRef<PropertyDefinitionRead[]>([]);
  const { mutate: setProperties } = useSetProperties();

  const savedIds = useMemo(() => new Set(saved.map((p) => p.property_id)), [saved]);

  const properties = useMemo<PropertySummary[]>(
    () => [
      ...saved,
      ...pending.filter((def) => !savedIds.has(def.id)).map(propertyStubFromDefinition),
    ],
    [saved, pending, savedIds]
  );
  const propertyIds = useMemo(() => properties.map((p) => p.property_id), [properties]);

  useEffect(() => {
    const next = pendingRef.current.filter((def) => !savedIds.has(def.id));
    if (next.length === pendingRef.current.length) return;
    pendingRef.current = next;
    setPending(next);
  }, [savedIds]);

  const add = useCallback(
    (definition: PropertyDefinitionRead) => {
      if (savedIds.has(definition.id)) return;
      if (!pendingRef.current.some((def) => def.id === definition.id)) {
        pendingRef.current = [...pendingRef.current, definition];
        setPending(pendingRef.current);
      }
      if (!Number.isFinite(id)) return;
      // Replace-all: everything already attached, and every property added
      // since — this one included — empty until it is filled in.
      setProperties({
        target,
        id,
        values: [
          ...saved.map((p) => ({ property_id: p.property_id, value: normalizePropertyValue(p) })),
          ...pendingRef.current
            .filter((def) => !savedIds.has(def.id))
            .map((def) => ({ property_id: def.id, value: null })),
        ],
      });
    },
    [target, id, saved, savedIds, setProperties]
  );

  return { properties, propertyIds, add };
};
