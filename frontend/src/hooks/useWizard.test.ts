import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useWizard } from "./useWizard";

type Step = "one" | "two" | "three";

describe("useWizard", () => {
  it("starts on the initial step with nowhere to go back to", () => {
    const { result } = renderHook(() => useWizard<Step>("one"));

    expect(result.current.step).toBe("one");
    expect(result.current.canGoBack).toBe(false);
  });

  it("walks forward and back along the route taken", () => {
    const { result } = renderHook(() => useWizard<Step>("one"));

    act(() => result.current.go("two"));
    act(() => result.current.go("three"));
    expect(result.current.step).toBe("three");

    act(() => result.current.back());
    expect(result.current.step).toBe("two");

    act(() => result.current.back());
    expect(result.current.step).toBe("one");
    expect(result.current.canGoBack).toBe(false);
  });

  it("records nothing for a walk to the step already showing", () => {
    const { result } = renderHook(() => useWizard<Step>("one"));

    act(() => result.current.go("two"));
    act(() => result.current.go("two"));

    act(() => result.current.back());
    expect(result.current.step).toBe("one");
    expect(result.current.canGoBack).toBe(false);
  });

  it("ignores back on an empty trail", () => {
    const { result } = renderHook(() => useWizard<Step>("one"));

    act(() => result.current.back());

    expect(result.current.step).toBe("one");
    expect(result.current.canGoBack).toBe(false);
  });

  it("commit drops the trail, so there is no way back out", () => {
    const { result } = renderHook(() => useWizard<Step>("one"));

    act(() => result.current.go("two"));
    expect(result.current.canGoBack).toBe(true);

    act(() => result.current.commit("three"));
    expect(result.current.canGoBack).toBe(false);

    act(() => result.current.back());
    expect(result.current.step).toBe("three");
  });

  it("reset returns to the initial step and clears the trail", () => {
    const { result } = renderHook(() => useWizard<Step>("one"));

    act(() => result.current.go("two"));
    act(() => result.current.go("three"));
    act(() => result.current.reset());

    expect(result.current.step).toBe("one");
    expect(result.current.canGoBack).toBe(false);
  });

  // The export wizard reaches one confirm step from two different places, and
  // used to restate which one it came from. These two cases are that graph.
  describe("a step reached from either of two branches", () => {
    type ExportStep = "mode" | "backup" | "report" | "confirm";

    it("returns to backup when that is the way it came", () => {
      const { result } = renderHook(() => useWizard<ExportStep>("mode"));

      act(() => result.current.go("backup"));
      act(() => result.current.go("confirm"));
      act(() => result.current.back());

      expect(result.current.step).toBe("backup");
    });

    it("returns to report when that is the way it came", () => {
      const { result } = renderHook(() => useWizard<ExportStep>("mode"));

      act(() => result.current.go("report"));
      act(() => result.current.go("confirm"));
      act(() => result.current.back());

      expect(result.current.step).toBe("report");
    });

    it("walks all the way back out through either branch", () => {
      const { result } = renderHook(() => useWizard<ExportStep>("mode"));

      act(() => result.current.go("report"));
      act(() => result.current.go("confirm"));
      act(() => result.current.back());
      act(() => result.current.back());

      expect(result.current.step).toBe("mode");
      expect(result.current.canGoBack).toBe(false);
    });
  });
});
