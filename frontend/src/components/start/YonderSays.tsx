import excited from "@/assets/yonder/excited.svg";
import farewell from "@/assets/yonder/farewell.svg";
import idle from "@/assets/yonder/idle.svg";
import proud from "@/assets/yonder/proud.svg";
import talking from "@/assets/yonder/talking.svg";
import thinking from "@/assets/yonder/thinking.svg";
import winking from "@/assets/yonder/winking.svg";

const POSES = { excited, farewell, idle, proud, talking, thinking, winking } as const;

export type YonderPose = keyof typeof POSES;

/**
 * Yonder, hosting a step: the pose for it and, when he has something to say,
 * a speech bubble beside him. The bubble is the step's orienting line, so it
 * is ordinary text; the picture is decoration.
 *
 * Remount it (a `key` per step) and he hops in again.
 */
export const YonderSays = ({ pose, line }: { pose: YonderPose; line?: string | null }) => (
  <div className="flex items-end gap-2">
    <img
      src={POSES[pose]}
      alt=""
      aria-hidden="true"
      className="h-16 w-16 shrink-0 motion-safe:animate-[yonder-hop_0.5s_ease-out]"
    />
    {line ? (
      <p className="relative mb-3 min-w-0 rounded-2xl rounded-bl-sm border bg-background px-3 py-2 text-foreground text-sm shadow-sm motion-safe:animate-[yonder-bubble_0.3s_ease-out_0.15s_both]">
        {line}
      </p>
    ) : null}
  </div>
);
