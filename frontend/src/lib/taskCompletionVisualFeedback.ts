// Single source of truth for the "task completion visual feedback" preference
// on the frontend. Mirror of the allowed values in
// backend/app/api/v1/endpoints/users.py (TASK_COMPLETION_VISUAL_FEEDBACK_VALUES).

export const TASK_COMPLETION_VISUAL_FEEDBACK_VALUES = [
  "none",
  "confetti",
  "heart",
  "d20",
  "gold_coin",
  "random",
] as const;

export type TaskCompletionVisualFeedback = (typeof TASK_COMPLETION_VISUAL_FEEDBACK_VALUES)[number];

// Pool the `random` option draws from. Excludes `none` (defeats the point)
// and `random` itself (would loop).
export const RANDOMIZABLE_EFFECTS = ["confetti", "heart", "d20", "gold_coin"] as const;

export type ResolvedEffect = (typeof RANDOMIZABLE_EFFECTS)[number];

const VALID_VALUES = new Set<string>(TASK_COMPLETION_VISUAL_FEEDBACK_VALUES);

export const parseTaskCompletionVisualFeedback = (
  raw: string | null | undefined
): TaskCompletionVisualFeedback => {
  if (raw && VALID_VALUES.has(raw)) {
    return raw as TaskCompletionVisualFeedback;
  }
  return "none";
};

// Map a stored preference to the actual effect that should fire right now.
// `none` → null (caller should skip), `random` → uniformly random element of
// the pool, anything else → echo input.
export const resolveEffect = (value: TaskCompletionVisualFeedback): ResolvedEffect | null => {
  if (value === "none") return null;
  if (value === "random") {
    const idx = Math.floor(Math.random() * RANDOMIZABLE_EFFECTS.length);
    return RANDOMIZABLE_EFFECTS[idx];
  }
  return value;
};

// Custom event channel — matches the AUTH_UNAUTHORIZED_EVENT pattern in
// src/api/client.ts. Carries the resolved effect (already random-resolved)
// in `event.detail.effect`.
export const TASK_COMPLETION_EVENT = "initiative:task-completion-feedback";

export interface TaskCompletionEventDetail {
  effect: ResolvedEffect;
}

export const dispatchTaskCompletionVisualFeedback = (value: TaskCompletionVisualFeedback): void => {
  if (typeof window === "undefined") return;
  const effect = resolveEffect(value);
  if (!effect) return;
  window.dispatchEvent(
    new CustomEvent<TaskCompletionEventDetail>(TASK_COMPLETION_EVENT, {
      detail: { effect },
    })
  );
};

// Last user-pointer position (viewport pixels). Updated by the global listener
// installed inside <TaskCompletionEffectHost />. Falls back to viewport center
// when no pointer interaction has happened yet (e.g. status changed via a
// keyboard shortcut on first load).
let lastPointerX: number | null = null;
let lastPointerY: number | null = null;

export const recordPointer = (x: number, y: number): void => {
  lastPointerX = x;
  lastPointerY = y;
};

export const getLastPointer = (): { x: number; y: number } => {
  if (typeof window === "undefined") {
    return { x: 0, y: 0 };
  }
  if (lastPointerX === null || lastPointerY === null) {
    return { x: window.innerWidth / 2, y: window.innerHeight / 2 };
  }
  return { x: lastPointerX, y: lastPointerY };
};
