import { useCallback, useMemo, useState } from "react";

/**
 * Multi-select state for a card/grid list (projects, queues, counter groups, …).
 * Selection is a mode you enter explicitly — cards become checkboxes and their
 * links stop navigating while it's active.
 *
 * Selected items are stored **by value**, not derived from the current page, so a
 * selection survives pagination/filtering: pick items on page 1, page to page 2,
 * pick more, and all of them are acted on together.
 */
export function useGridSelection<T extends { id: number }>() {
  const [active, setActive] = useState(false);
  const [selectedMap, setSelectedMap] = useState<Map<number, T>>(new Map());

  const selectedItems = useMemo(() => [...selectedMap.values()], [selectedMap]);
  const selectedIds = useMemo(() => new Set(selectedMap.keys()), [selectedMap]);

  const toggle = useCallback((item: T) => {
    setSelectedMap((prev) => {
      const next = new Map(prev);
      if (next.has(item.id)) next.delete(item.id);
      else next.set(item.id, item);
      return next;
    });
  }, []);

  const clear = useCallback(() => setSelectedMap(new Map()), []);

  const enter = useCallback(() => setActive(true), []);
  const exit = useCallback(() => {
    setActive(false);
    setSelectedMap(new Map());
  }, []);

  return { active, selectedIds, selectedItems, toggle, clear, enter, exit };
}
