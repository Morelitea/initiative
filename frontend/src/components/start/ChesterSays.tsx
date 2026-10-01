import excited from "@/assets/chester/excited.svg";
import farewell from "@/assets/chester/farewell.svg";
import idle from "@/assets/chester/idle.svg";
import proud from "@/assets/chester/proud.svg";
import talking from "@/assets/chester/talking.svg";
import thinking from "@/assets/chester/thinking.svg";
import winking from "@/assets/chester/winking.svg";

const POSES = { excited, farewell, idle, proud, talking, thinking, winking } as const;

export type ChesterPose = keyof typeof POSES;

/**
 * Chester, hosting a step: the pose for it and, when he has something to say,
 * a speech bubble beside him. The bubble is the step's orienting line, so it
 * is ordinary text; the picture is decoration.
 *
 * Remount it (a `key` per step) and he hops in again.
 */
export const ChesterSays = ({ pose, line }: { pose: ChesterPose; line?: string | null }) => (
  <div className="flex items-end gap-2">
    <img
      src={POSES[pose]}
      alt=""
      aria-hidden="true"
      className="h-16 w-16 shrink-0 motion-safe:animate-[chester-hop_0.5s_ease-out]"
    />
    {line ? (
      <p className="relative mb-3 min-w-0 rounded-2xl rounded-bl-sm border bg-background px-3 py-2 text-foreground text-sm shadow-sm motion-safe:animate-[chester-bubble_0.3s_ease-out_0.15s_both]">
        {line}
      </p>
    ) : null}
  </div>
);
