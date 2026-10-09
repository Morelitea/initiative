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

import type { TaskListRead, TaskRead } from "../../api/generated/initiativeAPI.schemas.ts";
import type { TaskCardContext, TaskPageContext } from "../../components/tasks/parts.tsx";

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
    // The context sits in a tuple so that a section with none still reads as undefined.
    definition as Definition & { readonly __data?: Data; readonly __context?: [Context] };

export const SECTIONS = {
  /**
   * A task on a board. Its parts are named as the board's Fields menu names
   * them, so the fields a reader turns off are the parts it hides.
   */
  "task.card": defineSection<{ task: TaskListRead }, TaskCardContext>()({
    data: { task: "TaskListRead" },
    parts: {
      title: { required: true },
      description: {},
      assignees: {},
      startDate: {},
      dueDate: {},
      recurrence: {},
      checklist: {},
      priority: {},
      comments: {},
      blockers: {},
      tags: {},
      properties: {},
    },
  }),
  /** The whole task page, one field per part so a theme can hide any one. */
  "task.page": defineSection<{ task: TaskRead }, TaskPageContext>()({
    data: { task: "TaskRead" },
    parts: {
      title: { required: true },
      actions: { required: true },
      breadcrumb: {},
      byline: {},
      notice: {},
      description: {},
      status: {},
      priority: {},
      dates: {},
      recurrence: {},
      assignees: {},
      tags: {},
      properties: {},
      checklist: {},
      relations: {},
      case: {},
      comments: {},
    },
  }),
} satisfies Record<string, SectionDefinition>;

export type SectionName = keyof typeof SECTIONS;

type DefinitionOf<S extends SectionName> = (typeof SECTIONS)[S];

export type SectionData<S extends SectionName> = NonNullable<DefinitionOf<S>["__data"]>;
export type SectionContext<S extends SectionName> = NonNullable<DefinitionOf<S>["__context"]>[0];

export type PartName<S extends SectionName> = keyof DefinitionOf<S>["parts"] & string;

/** What a part receives: the section's data, and whatever its route shares. */
export interface PartProps<S extends SectionName> {
  data: SectionData<S>;
  context: SectionContext<S>;
  /**
   * The classes the template gives the part, for its outermost element: a part
   * has no wrapper. One that draws a list of elements, such as chips, has no
   * single element to give them to and leaves them off.
   */
  className?: string;
}

/** Every part of a section, each a component; `tsc` fails on a missing or extra one. */
export type PartsFor<S extends SectionName> = {
  [P in keyof DefinitionOf<S>["parts"]]: ComponentType<PartProps<S>>;
};
