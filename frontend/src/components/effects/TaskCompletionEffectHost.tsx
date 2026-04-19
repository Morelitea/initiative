import { useCallback, useEffect, useState } from "react";

import {
  TASK_COMPLETION_EVENT,
  type TaskCompletionEventDetail,
  getLastPointer,
  recordPointer,
} from "@/lib/taskCompletionVisualFeedback";

import { D20Roller } from "./D20Roller";
import { HeartFloater } from "./HeartFloater";
import { runConfetti } from "./runConfetti";

interface ActiveEffect {
  // Unique key per fire so back-to-back triggers each render fresh — React
  // unmounts and remounts the child cleanly even when the same effect repeats.
  id: number;
  kind: "heart" | "d20";
  x: number;
  y: number;
}

let nextId = 0;

// Mounted once at the top of the app (next to <Toaster /> in main.tsx).
// Listens for our custom event channel and renders the chosen effect. Confetti
// variants render directly to a canvas via canvas-confetti so they don't need
// any DOM child here. Heart and d20 mount as small overlays.
export const TaskCompletionEffectHost = () => {
  const [active, setActive] = useState<ActiveEffect | null>(null);

  // Track the latest pointer position globally. Used by HeartFloater to spawn
  // at the click site, and by runConfetti to choose its origin.
  useEffect(() => {
    const handlePointer = (event: PointerEvent) => {
      recordPointer(event.clientX, event.clientY);
    };
    window.addEventListener("pointerdown", handlePointer, { passive: true });
    window.addEventListener("pointermove", handlePointer, { passive: true });
    return () => {
      window.removeEventListener("pointerdown", handlePointer);
      window.removeEventListener("pointermove", handlePointer);
    };
  }, []);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<TaskCompletionEventDetail>).detail;
      if (!detail) return;
      switch (detail.effect) {
        case "confetti":
          runConfetti("default");
          return;
        case "gold_coin":
          runConfetti("gold_coin");
          return;
        case "heart": {
          const pointer = getLastPointer();
          setActive({ id: ++nextId, kind: "heart", x: pointer.x, y: pointer.y });
          return;
        }
        case "d20": {
          const pointer = getLastPointer();
          setActive({ id: ++nextId, kind: "d20", x: pointer.x, y: pointer.y });
          return;
        }
      }
    };
    window.addEventListener(TASK_COMPLETION_EVENT, handler);
    return () => window.removeEventListener(TASK_COMPLETION_EVENT, handler);
  }, []);

  const handleDone = useCallback(() => {
    setActive(null);
  }, []);

  if (!active) return null;

  if (active.kind === "heart") {
    return <HeartFloater key={active.id} x={active.x} y={active.y} onDone={handleDone} />;
  }

  return <D20Roller key={active.id} x={active.x} y={active.y} onDone={handleDone} />;
};
