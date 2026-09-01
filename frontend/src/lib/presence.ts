import { Presence } from "@/api/generated/initiativeAPI.schemas";

/**
 * How someone appears, and how that is drawn.
 *
 * One list, in the order the menu offers them, so a state added to the API
 * enum has exactly one place to be described rather than a colour in one file
 * and a label in another.
 *
 * `idle` sits in it twice over: it is what `online` becomes on its own once a
 * person's tabs go quiet, and it is also a thing they may pick outright.
 */
export const PRESENCE_ORDER = [
  Presence.online,
  Presence.idle,
  Presence.busy,
  Presence.offline,
] as const;

/**
 * The dot's colour, per state.
 *
 * The word goes with it wherever it is drawn, because a colour on its own is
 * not something everyone can read.
 */
export const PRESENCE_COLOR: Record<Presence, string> = {
  [Presence.online]: "bg-emerald-500",
  [Presence.idle]: "bg-amber-400",
  [Presence.busy]: "bg-rose-500",
  [Presence.offline]: "bg-muted-foreground/40",
};

/** The `profiles:presence.*` key naming a state. */
export const presenceLabelKey = (presence: Presence) => `presence.${presence}` as const;

/** The `profiles:presence.help.*` key saying what picking it does. */
export const presenceHelpKey = (presence: Presence) => `presence.help.${presence}` as const;
