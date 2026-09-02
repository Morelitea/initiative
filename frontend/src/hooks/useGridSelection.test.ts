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

  it("shift-click selects the run between the anchor and the clicked card", () => {
    const items = [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }];
    const { result } = renderHook(() => useGridSelection(items));

    act(() => result.current.enter());
    act(() => result.current.toggle({ id: 1 }));
    act(() => result.current.toggle({ id: 4 }, { extend: true }));

    expect([...result.current.selectedIds].sort()).toEqual([1, 2, 3, 4]);
  });

  it("shift-click clears the run when the anchor was just deselected", () => {
    const items = [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }];
    const { result } = renderHook(() => useGridSelection(items));

    act(() => result.current.toggle({ id: 1 }));
    act(() => result.current.toggle({ id: 4 }, { extend: true }));
    // Deselect 3, then sweep back up to 1 — the anchor's state paints the run.
    act(() => result.current.toggle({ id: 3 }));
    act(() => result.current.toggle({ id: 1 }, { extend: true }));

    expect([...result.current.selectedIds]).toEqual([4]);
  });

  it("shift-click is a plain toggle before anything has been clicked", () => {
    const items = [{ id: 1 }, { id: 2 }, { id: 3 }];
    const { result } = renderHook(() => useGridSelection(items));

    act(() => result.current.toggle({ id: 3 }, { extend: true }));

    expect([...result.current.selectedIds]).toEqual([3]);
  });

  it("forgets the anchor on exit, so the next list starts fresh", () => {
    const items = [{ id: 1 }, { id: 2 }, { id: 3 }];
    const { result } = renderHook(() => useGridSelection(items));

    act(() => result.current.toggle({ id: 1 }));
    act(() => result.current.exit());
    act(() => result.current.enter());
    act(() => result.current.toggle({ id: 3 }, { extend: true }));

    expect([...result.current.selectedIds]).toEqual([3]);
  });
});
