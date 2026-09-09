import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useServerForm } from "./useServerForm";

interface Entity {
  name: string;
  description: string | null;
}

const derive = (entity: Entity | undefined) => ({
  name: entity?.name ?? "",
  description: entity?.description ?? "",
});

describe("useServerForm", () => {
  it("fills in from the entity once it lands", () => {
    const { result, rerender } = renderHook(({ entity }) => useServerForm(entity, derive), {
      initialProps: { entity: undefined as Entity | undefined },
    });
    expect(result.current.values).toEqual({ name: "", description: "" });

    rerender({ entity: { name: "Roadmap", description: null } });

    expect(result.current.values).toEqual({ name: "Roadmap", description: "" });
    expect(result.current.edited).toBe(false);
  });

  it("follows a later answer while nothing is unsaved", () => {
    const { result, rerender } = renderHook(({ entity }) => useServerForm(entity, derive), {
      initialProps: { entity: { name: "Roadmap", description: null } as Entity | undefined },
    });

    rerender({ entity: { name: "Renamed by somebody else", description: null } });

    expect(result.current.values.name).toBe("Renamed by somebody else");
  });

  it("keeps unsaved work when a later answer would overwrite it", () => {
    const { result, rerender } = renderHook(({ entity }) => useServerForm(entity, derive), {
      initialProps: { entity: { name: "Roadmap", description: null } as Entity | undefined },
    });

    act(() => result.current.set({ name: "Half-written" }));
    rerender({ entity: { name: "Renamed by somebody else", description: null } });

    expect(result.current.values.name).toBe("Half-written");
    expect(result.current.edited).toBe(true);
  });

  it("goes back to following the server once the work is saved", () => {
    const { result, rerender } = renderHook(({ entity }) => useServerForm(entity, derive), {
      initialProps: { entity: { name: "Roadmap", description: null } as Entity | undefined },
    });

    act(() => result.current.set({ name: "Half-written" }));
    act(() => result.current.settle());
    expect(result.current.edited).toBe(false);
    // Still showing what was typed — settling does not undo it.
    expect(result.current.values.name).toBe("Half-written");

    rerender({ entity: { name: "Half-written", description: "and described" } });

    expect(result.current.values.description).toBe("and described");
  });

  it("leaves the fields alone when the same answer arrives again", () => {
    const entity: Entity = { name: "Roadmap", description: null };
    const { result, rerender } = renderHook(({ entity }) => useServerForm(entity, derive), {
      initialProps: { entity: entity as Entity | undefined },
    });

    act(() => result.current.set({ name: "Half-written" }));
    // The identity React Query preserves when nothing about the answer moved.
    rerender({ entity });

    expect(result.current.values.name).toBe("Half-written");
  });

  it("does not mistake a rebuilt list of ids for a change", () => {
    const { result, rerender } = renderHook(
      ({ ids }) => useServerForm({ ids }, (source) => ({ ids: source?.ids ?? [] })),
      { initialProps: { ids: [1, 2, 3] } }
    );

    act(() => result.current.set({ ids: [1, 2] }));
    // Same ids, new array — every render of a real page rebuilds one of these.
    rerender({ ids: [1, 2, 3] });

    expect(result.current.values.ids).toEqual([1, 2]);
  });

  it("follows a list that actually changed", () => {
    const { result, rerender } = renderHook(
      ({ ids }) => useServerForm({ ids }, (source) => ({ ids: source?.ids ?? [] })),
      { initialProps: { ids: [1, 2, 3] } }
    );

    rerender({ ids: [1, 2, 3, 4] });

    expect(result.current.values.ids).toEqual([1, 2, 3, 4]);
  });

  it("edits one field without disturbing the others", () => {
    const { result } = renderHook(() =>
      useServerForm({ name: "Roadmap", description: "A description" } as Entity | undefined, derive)
    );

    act(() => result.current.set({ name: "Renamed" }));

    expect(result.current.values).toEqual({ name: "Renamed", description: "A description" });
  });
});
