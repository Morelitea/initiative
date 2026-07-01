import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useGridSelection } from "./useGridSelection";

const items = [{ id: 1 }, { id: 2 }, { id: 3 }];

describe("useGridSelection", () => {
  it("toggles ids and derives selectedItems from the live list", () => {
    const { result } = renderHook(() => useGridSelection(items));

    expect(result.current.active).toBe(false);
    act(() => result.current.enter());
    act(() => result.current.toggle(1));
    act(() => result.current.toggle(3));

    expect(result.current.active).toBe(true);
    expect(result.current.selectedItems.map((i) => i.id)).toEqual([1, 3]);

    act(() => result.current.toggle(1));
    expect(result.current.selectedItems.map((i) => i.id)).toEqual([3]);
  });

  it("exit clears selection and leaves selection mode", () => {
    const { result } = renderHook(() => useGridSelection(items));
    act(() => result.current.enter());
    act(() => result.current.toggle(2));
    act(() => result.current.exit());

    expect(result.current.active).toBe(false);
    expect(result.current.selectedItems).toEqual([]);
  });

  it("drops selected ids that are no longer in the list", () => {
    const { result, rerender } = renderHook(({ list }) => useGridSelection(list), {
      initialProps: { list: items },
    });
    act(() => result.current.toggle(2));
    expect(result.current.selectedItems.map((i) => i.id)).toEqual([2]);

    // Item 2 paginated/filtered away -> it silently drops from selectedItems.
    rerender({ list: [{ id: 1 }, { id: 3 }] });
    expect(result.current.selectedItems).toEqual([]);
  });
});
