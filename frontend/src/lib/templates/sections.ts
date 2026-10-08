/**
 * The sections: the regions of a community's screens that a template draws.
 *
 * Declared once, here. The compiler checks templates against this, the
 * renderer and `<Section>` are typed from it, and each tool's `parts.ts` is held
 * to it by `PartsFor`, so there is no second list to keep in step. A section
 * names:
 *
 * - `data`: the names a template reads and the API schema each holds, from the
 *   generated types, so a template is checked against what the API returns;
 * - `parts`: our components a template places, and which of them it must.
 *
 * Kept free of the browser and of `@/` imports, and its own imports name their
 * `.ts` files: the Vite plugin reads it in Node.
 */

import type { ComponentType } from "react";

export interface PartDefinition {
  /** A screen that cannot work without it, so no template may leave it out. */
  required?: boolean;
}

export interface SectionDefinition {
  /** Each name a template may read, and the API schema it holds. */
  data: Readonly<Record<string, string>>;
  parts: Readonly<Record<string, PartDefinition>>;
}

/**
 * Declare a section, with the data its route passes as a type argument beside
 * the schema names the compiler checks it against, so the two sit together.
 */
export const defineSection =
  <Data extends Record<string, unknown>, Context = undefined>() =>
  <const Definition extends SectionDefinition & { data: { [K in keyof Data]: string } }>(
    definition: Definition
  ) =>
    definition as Definition & { readonly __data?: Data; readonly __context?: Context };

export const SECTIONS = {} satisfies Record<string, SectionDefinition>;

export type SectionName = keyof typeof SECTIONS;

type DefinitionOf<S extends SectionName> = (typeof SECTIONS)[S];

export type SectionData<S extends SectionName> = NonNullable<DefinitionOf<S>["__data"]>;
export type SectionContext<S extends SectionName> = DefinitionOf<S>["__context"];

/** What a part receives: the section's data, and whatever its route shares. */
export interface PartProps<S extends SectionName> {
  data: SectionData<S>;
  context: SectionContext<S>;
}

/** Every part of a section, each a component; `tsc` fails on a missing or extra one. */
export type PartsFor<S extends SectionName> = {
  [P in keyof DefinitionOf<S>["parts"]]: ComponentType<PartProps<S>>;
};
