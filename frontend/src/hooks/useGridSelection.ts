import { useCallback, useMemo, useState } from "react";

/**
 * Multi-select state for a card/grid list (projects, queues, counter groups, …).
 * Selection is a mode you enter explicitly — cards become checkboxes and their
 * links stop navigating while it's active. `selectedItems` is derived from the
 * live list, so items that scroll/paginate away silently drop out of the result.
 */
export function useGridSelection<T extends { id: number }>(items: T[]) {
  const [active, setActive] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  const selectedItems = useMemo(
    () => items.filter((item) => selectedIds.has(item.id)),
    [items, selectedIds]
  );

  const toggle = useCallback((id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const clear = useCallback(() => setSelectedIds(new Set()), []);

  const enter = useCallback(() => setActive(true), []);
  const exit = useCallback(() => {
    setActive(false);
    setSelectedIds(new Set());
  }, []);

  return { active, selectedIds, selectedItems, toggle, clear, enter, exit };
}
