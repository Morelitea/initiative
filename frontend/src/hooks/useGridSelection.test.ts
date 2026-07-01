import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useGridSelection } from "./useGridSelection";

describe("useGridSelection", () => {
  it("toggles items and derives selectedItems/selectedIds", () => {
    const { result } = renderHook(() => useGridSelection<{ id: number }>());

    act(() => result.current.enter());
    act(() => result.current.toggle({ id: 1 }));
    act(() => result.current.toggle({ id: 3 }));

    expect(result.current.active).toBe(true);
    expect([...result.current.selectedIds].sort()).toEqual([1, 3]);
    expect(result.current.selectedItems.map((i) => i.id).sort()).toEqual([1, 3]);

    act(() => result.current.toggle({ id: 1 }));
    expect(result.current.selectedItems.map((i) => i.id)).toEqual([3]);
  });

  it("exit clears selection and leaves selection mode", () => {
    const { result } = renderHook(() => useGridSelection<{ id: number }>());
    act(() => result.current.enter());
    act(() => result.current.toggle({ id: 2 }));
    act(() => result.current.exit());

    expect(result.current.active).toBe(false);
    expect(result.current.selectedItems).toEqual([]);
  });

  it("persists selections by value across list changes (pagination)", () => {
    const { result } = renderHook(() => useGridSelection<{ id: number; name: string }>());

    // Select an item on "page 1", then one on "page 2" — the store keeps the
    // objects, so a selection never disappears when the visible list changes.
    act(() => result.current.toggle({ id: 1, name: "page1" }));
    act(() => result.current.toggle({ id: 9, name: "page2" }));

    expect(result.current.selectedItems.map((i) => i.id).sort()).toEqual([1, 9]);
    expect(result.current.selectedItems.find((i) => i.id === 1)?.name).toBe("page1");
  });
});
