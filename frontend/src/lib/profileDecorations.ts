/**
 * The catalog a profile's decorations are resolved against.
 *
 * A profile stores **ids**, never images: `{ banner: "core.aurora", frame:
 * "core.gold", badges: ["core.founder"] }`. This module is what turns one of
 * those ids into something to render — a lookup in the table below, so an id
 * that isn't in it resolves to nothing at all.
 *
 * Everything here ships with the app under `public/decorations/`, so wearing a
 * banner costs a community none of its upload allowance. The store is what will
 * grant ids beyond these; nothing about resolving one changes when it does.
 *
 * An id a deployment doesn't know renders as bare — which is the behaviour that
 * lets a profile keep wearing something the store has stopped offering.
 */

import type { ProfileDecorationsOutput } from "@/api/generated/initiativeAPI.schemas";

export type DecorationKind = "banner" | "frame" | "badge";

/** Every decoration this build ships, by the name its label is keyed under. */
type DecorationName =
  | "aurora"
  | "ember"
  | "parchment"
  | "gold"
  | "arcane"
  | "founder"
  | "storyteller"
  | "trailblazer";

export interface Decoration {
  id: string;
  kind: DecorationKind;
  /** Where the artwork is, relative to the app's root. */
  src: string;
  /** Key into the `profiles` namespace for this decoration's name. */
  labelKey: `decorations.${DecorationName}`;
}

const entry = (
  id: string,
  kind: DecorationKind,
  file: string,
  name: DecorationName
): Decoration => ({
  id,
  kind,
  src: `/decorations/${kind}s/${file}.svg`,
  labelKey: `decorations.${name}`,
});

/** The catalog, by id. */
export const DECORATIONS: Readonly<Record<string, Decoration>> = {
  "core.aurora": entry("core.aurora", "banner", "core-aurora", "aurora"),
  "core.ember": entry("core.ember", "banner", "core-ember", "ember"),
  "core.parchment": entry("core.parchment", "banner", "core-parchment", "parchment"),
  "core.gold": entry("core.gold", "frame", "core-gold", "gold"),
  "core.arcane": entry("core.arcane", "frame", "core-arcane", "arcane"),
  "core.founder": entry("core.founder", "badge", "core-founder", "founder"),
  "core.storyteller": entry("core.storyteller", "badge", "core-storyteller", "storyteller"),
  "core.trailblazer": entry("core.trailblazer", "badge", "core-trailblazer", "trailblazer"),
};

/** The decoration this id names, if this build has it and it is of that kind. */
export const resolveDecoration = (
  id: string | null | undefined,
  kind: DecorationKind
): Decoration | undefined => {
  if (!id) return undefined;
  const found = DECORATIONS[id];
  return found?.kind === kind ? found : undefined;
};

/** The badges a profile is wearing that this build can draw, in the order worn. */
export const resolveBadges = (
  decorations: ProfileDecorationsOutput | null | undefined
): Decoration[] =>
  (decorations?.badges ?? [])
    .map((id) => resolveDecoration(id, "badge"))
    .filter((badge): badge is Decoration => Boolean(badge));
