import { type RobotToastOptions, toast as robotToast } from "robot-toast";

import excitedSvg from "@/assets/chester/excited.svg";
import idleSvg from "@/assets/chester/idle.svg";
import proudSvg from "@/assets/chester/proud.svg";
import talkingSvg from "@/assets/chester/talking.svg";
import thinkingSvg from "@/assets/chester/thinking.svg";

type ChesterToastType = "default" | "success" | "error" | "warning" | "info" | "loading";

type ChesterToastPosition =
  | "top-left"
  | "top-center"
  | "top-right"
  | "bottom-left"
  | "bottom-center"
  | "bottom-right";

const VARIANT_BY_TYPE: Record<ChesterToastType, string> = {
  default: idleSvg,
  success: proudSvg,
  error: excitedSvg,
  warning: thinkingSvg,
  info: talkingSvg,
  loading: talkingSvg,
};

interface ChesterToastOptions {
  /** Custom dismissal handle. Sonner uses string|number; we accept both. */
  id?: string | number;
  /** ms to auto-dismiss; pass `Infinity` to keep open until dismissed. */
  duration?: number;
  /** Secondary line appended below the main message (Sonner parity). */
  description?: string;
  /** Override the auto-selected Chester variant with any imported SVG URL. */
  robotVariant?: string;
  position?: ChesterToastPosition;
  typeSpeed?: number;
  /** Sonner-style action; mapped to a single robot-toast button. */
  action?: { label: string; onClick: (e: MouseEvent) => void };
  /**
   * Fires when the toast closes for any reason (manual dismiss or auto-close).
   * Sonner's separate `onDismiss` / `onAutoClose` are not honored — robot-toast
   * exposes a single close hook with no way to distinguish the two.
   */
  onClose?: () => void;
}

type RobotToastType = "default" | "success" | "error" | "warning" | "info";

const idMap = new Map<string | number, number>();

const ROBOT_TYPE_BY_TYPE: Record<ChesterToastType, RobotToastType> = {
  default: "default",
  success: "success",
  error: "error",
  warning: "warning",
  info: "info",
  loading: "info",
};

/**
 * Auto-dismiss timing.
 *
 * robot-toast only starts its auto-close timer once the typewriter animation
 * finishes, so `autoClose` is the dwell time *after* the message is fully on
 * screen — not the total time it is visible. We budget a total reading time
 * from the content and hand robot-toast whatever is left once typing is done.
 *
 * The budget is a fixed cost for noticing the toast plus a per-character
 * reading allowance (50ms/char, roughly 240 wpm), clamped so short messages
 * still linger long enough to register and long ones don't camp on screen.
 */
const NOTICE_MS = 1_200;
const MS_PER_CHAR = 50;
const MAX_TOTAL_MS = 10_000;
/** Extra budget when the toast carries a button the reader may want to press. */
const ACTION_MS = 2_000;
/** Never leave less than this much time after the message finishes typing. */
const MIN_DWELL_MS = 1_200;
/** Floor on total on-screen time, per type — warnings and errors sit longer. */
const MIN_TOTAL_MS_BY_TYPE: Record<ChesterToastType, number> = {
  default: 3_000,
  success: 3_000,
  info: 3_000,
  loading: 3_000,
  warning: 4_500,
  error: 5_000,
};

/** Dwell time (ms) to hand robot-toast for a message it will type at `typeSpeed`. */
const computeAutoClose = (
  message: string,
  type: ChesterToastType,
  typeSpeed: number,
  hasAction: boolean
): number => {
  const budget = NOTICE_MS + message.length * MS_PER_CHAR + (hasAction ? ACTION_MS : 0);
  const total = Math.min(Math.max(budget, MIN_TOTAL_MS_BY_TYPE[type]), MAX_TOTAL_MS);
  const typingMs = message.length * typeSpeed;
  return Math.max(total - typingMs, MIN_DWELL_MS);
};

const buildInput = (
  message: string,
  type: ChesterToastType,
  opts?: ChesterToastOptions
): RobotToastOptions => {
  const text = opts?.description ? `${message}\n${opts.description}` : message;
  const typeSpeed = opts?.typeSpeed ?? 20;
  const input: RobotToastOptions = {
    message: text,
    type: ROBOT_TYPE_BY_TYPE[type],
    robotVariant: opts?.robotVariant ?? VARIANT_BY_TYPE[type],
    position: opts?.position ?? "bottom-center",
    typeSpeed,
    // Cap how many toasts are visible at once; the rest queue and appear as
    // slots free up (robot-toast reads this per call, falling back to its
    // unlimited default otherwise).
    limit: 2,
  };
  if (opts?.duration !== undefined) {
    input.autoClose = Number.isFinite(opts.duration) ? opts.duration : false;
  } else {
    input.autoClose = computeAutoClose(text, type, typeSpeed, Boolean(opts?.action));
  }
  if (opts?.action) {
    input.buttons = [{ label: opts.action.label, onClick: opts.action.onClick }];
  }
  const userId = opts?.id;
  const userOnClose = opts?.onClose;
  if (userId !== undefined || userOnClose) {
    input.onClose = () => {
      if (userId !== undefined) idMap.delete(userId);
      userOnClose?.();
    };
  }
  return input;
};

const fire = (message: string, type: ChesterToastType, opts?: ChesterToastOptions): number => {
  const internalId = robotToast(buildInput(message, type, opts));
  if (opts?.id !== undefined) idMap.set(opts.id, internalId);
  return internalId;
};

interface PromiseMessages<T> {
  loading: string;
  success: string | ((value: T) => string);
  error: string | ((err: unknown) => string);
}

interface ChesterToast {
  (message: string, options?: ChesterToastOptions): number;
  success(message: string, options?: ChesterToastOptions): number;
  error(message: string, options?: ChesterToastOptions): number;
  warning(message: string, options?: ChesterToastOptions): number;
  info(message: string, options?: ChesterToastOptions): number;
  message(message: string, options?: ChesterToastOptions): number;
  loading(message: string, options?: ChesterToastOptions): number;
  dismiss(id?: string | number): void;
  promise<T>(
    promise: Promise<T>,
    msgs: PromiseMessages<T>,
    options?: ChesterToastOptions
  ): Promise<T>;
}

const toast = ((message: string, options?: ChesterToastOptions) =>
  fire(message, "default", options)) as ChesterToast;

toast.success = (message, options) => fire(message, "success", options);
toast.error = (message, options) => fire(message, "error", options);
toast.warning = (message, options) => fire(message, "warning", options);
toast.info = (message, options) => fire(message, "info", options);
toast.message = (message, options) => fire(message, "default", options);
toast.loading = (message, options) =>
  fire(message, "loading", { ...options, duration: options?.duration ?? Infinity });

toast.dismiss = (id) => {
  if (id === undefined) {
    robotToast.closeAll();
    idMap.clear();
    return;
  }
  const internalId = idMap.get(id);
  if (internalId !== undefined) {
    robotToast.closeById(internalId);
    idMap.delete(id);
  }
};

toast.promise = async <T>(
  promise: Promise<T>,
  msgs: PromiseMessages<T>,
  options?: ChesterToastOptions
) => {
  const loadingId = fire(msgs.loading, "loading", { ...options, duration: Infinity });
  try {
    const value = await promise;
    robotToast.closeById(loadingId);
    fire(
      typeof msgs.success === "function" ? msgs.success(value) : msgs.success,
      "success",
      options
    );
    return value;
  } catch (err) {
    robotToast.closeById(loadingId);
    fire(typeof msgs.error === "function" ? msgs.error(err) : msgs.error, "error", options);
    throw err;
  }
};

export type { ChesterToastOptions, ChesterToastType };
export { computeAutoClose, toast };
