import { useCallback, useEffect, useMemo, useState } from "react";

import type {
  PropertyDefinitionRead,
  PropertySummary,
} from "@/api/generated/initiativeAPI.schemas";

import { propertyStubFromDefinition } from "./PropertyFields";

/**
 * A row's saved properties plus the ones just added to it, for a
 * `PropertyList` beside an `AddPropertyButton`.
 *
 * An added property shows at once with no value. It is saved by the
 * `PropertyList` — handed the added ids as `unsaved` — together with every
 * value the list holds, so an addition never writes over a value someone just
 * entered. It drops out of the pending set once the server's copy of the row
 * carries it.
 */
export const usePendingProperties = (saved: PropertySummary[]) => {
  const [pending, setPending] = useState<PropertyDefinitionRead[]>([]);

  const savedIds = useMemo(() => new Set(saved.map((p) => p.property_id)), [saved]);
  const unsaved = useMemo(
    () => pending.filter((def) => !savedIds.has(def.id)),
    [pending, savedIds]
  );

  const properties = useMemo<PropertySummary[]>(
    () => [...saved, ...unsaved.map(propertyStubFromDefinition)],
    [saved, unsaved]
  );
  const propertyIds = useMemo(() => properties.map((p) => p.property_id), [properties]);
  const unsavedIds = useMemo(() => unsaved.map((def) => def.id), [unsaved]);

  useEffect(() => {
    setPending((prev) => {
      const next = prev.filter((def) => !savedIds.has(def.id));
      return next.length === prev.length ? prev : next;
    });
  }, [savedIds]);

  const add = useCallback(
    (definition: PropertyDefinitionRead) => {
      if (savedIds.has(definition.id)) return;
      setPending((prev) =>
        prev.some((def) => def.id === definition.id) ? prev : [...prev, definition]
      );
    },
    [savedIds]
  );

  // An addition the server refused comes off again, so it can be added anew.
  const discard = useCallback((ids: number[]) => {
    setPending((prev) => prev.filter((def) => !ids.includes(def.id)));
  }, []);

  return { properties, propertyIds, unsavedIds, add, discard };
};
