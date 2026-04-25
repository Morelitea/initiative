import { toast as robotToast } from "robot-toast";

import excitedSvg from "@/assets/chester/excited.svg";
import idleSvg from "@/assets/chester/idle.svg";
import proudSvg from "@/assets/chester/proud.svg";
import talkingSvg from "@/assets/chester/talking.svg";
import thinkingSvg from "@/assets/chester/thinking.svg";

export type ChesterToastType = "default" | "success" | "error" | "warning" | "info" | "loading";

export type ChesterToastPosition =
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

export interface ChesterToastOptions {
  /** Custom dismissal handle. Sonner uses string|number; we accept both. */
  id?: string | number;
  /** ms to auto-dismiss; pass `Infinity` to keep open until dismissed. */
  duration?: number;
  /** Secondary line appended below the main message (Sonner parity). */
  description?: string;
  /** Override the auto-selected Chester variant with any imported SVG URL. */
  robotVariant?: string;
  position?: ChesterToastPosition;
  /** Sonner-style action; mapped to a single robot-toast button. */
  action?: { label: string; onClick: (e: MouseEvent) => void };
  onDismiss?: () => void;
  onAutoClose?: () => void;
}

type RobotToastType = "default" | "success" | "error" | "warning" | "info";

interface RobotToastInput {
  message: string;
  type: RobotToastType;
  robotVariant: string;
  position?: ChesterToastPosition;
  autoClose?: number | boolean;
  buttons?: { label: string; onClick: (e: MouseEvent) => void }[];
  onClose?: () => void;
}

const idMap = new Map<string | number, number>();

const ROBOT_TYPE_BY_TYPE: Record<ChesterToastType, RobotToastType> = {
  default: "default",
  success: "success",
  error: "error",
  warning: "warning",
  info: "info",
  loading: "info",
};

const buildInput = (
  message: string,
  type: ChesterToastType,
  opts?: ChesterToastOptions
): RobotToastInput => {
  const input: RobotToastInput = {
    message: opts?.description ? `${message}\n${opts.description}` : message,
    type: ROBOT_TYPE_BY_TYPE[type],
    robotVariant: opts?.robotVariant ?? VARIANT_BY_TYPE[type],
  };
  if (opts?.position) input.position = opts.position;
  if (opts?.duration !== undefined) {
    input.autoClose = Number.isFinite(opts.duration) ? opts.duration : false;
  }
  if (opts?.action) {
    input.buttons = [{ label: opts.action.label, onClick: opts.action.onClick }];
  }
  const onClose = opts?.onDismiss ?? opts?.onAutoClose;
  if (onClose) input.onClose = onClose;
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

export { toast };
