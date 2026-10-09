/**
 * What a template may contain, read from the plug-in contract.
 *
 * The contract's `templates` block is the template language's vocabulary as
 * data, written in the plug-in SDK and vendored here
 * (`backend/scripts/refresh_plugin_kit.py`). One list holds for every template:
 * Tavern's, the built-in widgets' and a plug-in's. A plug-in's template is held
 * to two more limits: only the contract's classes, which the stylesheet carries,
 * and no `t()`, since a plug-in's words are its own `strings`.
 *
 * Kept free of the browser and of `@/` imports: the Vite plugin reads it in Node.
 */

import contract from "../../contract/manifest.contract.json" with { type: "json" };

const { templates, caps } = contract;

/** Structure and text, and nothing that runs, submits or frames, with each one's own attributes. */
export const ELEMENT_ATTRIBUTES: ReadonlyMap<string, ReadonlySet<string>> = new Map(
  Object.entries(templates.elements).map(([element, attributes]) => [
    element,
    new Set<string>(attributes),
  ])
);

/** Attributes any element may carry, as given or bound. */
export const GLOBAL_ATTRIBUTES: ReadonlySet<string> = new Set(templates.globalAttributes);
/** Families any element may carry: `aria-*`, `data-*`. */
export const ATTRIBUTE_PREFIXES: readonly string[] = templates.attributePrefixes;
/** Initiative's own, for marking sections and parts; a template never sets them. */
export const RESERVED_ATTRIBUTES: ReadonlySet<string> = new Set(templates.reservedAttributes);
/** Only ever bound: a map of custom properties, typed when rendered. */
export const BOUND_ONLY: ReadonlySet<string> = new Set(templates.boundOnlyAttributes);
export const DIRECTIVES: ReadonlySet<string> = new Set(templates.directives);

/** The functions an expression may call. Initiative's own templates may also call `t()`. */
export const FUNCTIONS: ReadonlySet<string> = new Set(templates.functions);

/** The widget elements, by name, and the props each takes as a template writes them. */
export const WIDGET_ELEMENT_PROPS: Readonly<Record<string, readonly string[]>> =
  templates.widgetElements;

/** The elements only a plug-in block may place, and the props each takes. */
export const BLOCK_ELEMENT_PROPS: Readonly<Record<string, readonly string[]>> =
  templates.blockElements;

/** The most tasks one call for a block's rows may name. */
export const BLOCK_SUBJECT_IDS: number = caps.blockSubjectIds;

/** The classes a plug-in's template may use, all of which the stylesheet carries. */
export const PLUGIN_CLASSES: ReadonlySet<string> = new Set(templates.classes);

export const LIMITS = {
  /** `for` inside `for`, at most this deep: each level repeats everything inside it. */
  loopDepth: caps.templateLoopDepth,
  expressionLength: caps.templateExpressionLength,
  expressionNodes: caps.templateExpressionNodes,
  comprehensionDepth: caps.templateComprehensionDepth,
  renderedNodes: caps.templateRenderedNodes,
} as const;
