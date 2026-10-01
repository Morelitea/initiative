import { useCallback, useEffect, useMemo, useState } from "react";

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
    setPending((prev) => {
      if (prev.length === 0) return prev;
      const next = prev.filter((def) => !savedIds.has(def.id));
      return next.length === prev.length ? prev : next;
    });
  }, [savedIds]);

  const add = useCallback(
    (definition: PropertyDefinitionRead) => {
      setPending((prev) =>
        prev.some((def) => def.id === definition.id) ? prev : [...prev, definition]
      );
      if (!Number.isFinite(id) || savedIds.has(definition.id)) return;
      // Replace-all: everything already attached, plus the new one, empty.
      setProperties({
        target,
        id,
        values: [
          ...saved.map((p) => ({ property_id: p.property_id, value: normalizePropertyValue(p) })),
          { property_id: definition.id, value: null },
        ],
      });
    },
    [target, id, saved, savedIds, setProperties]
  );

  return { properties, propertyIds, add };
};
