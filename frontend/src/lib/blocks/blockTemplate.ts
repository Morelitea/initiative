/**
 * A plug-in block's template, compiled against what it may read.
 *
 * A block draws one task, so its template reads `task` (the fields both task
 * sections hold), `answer` (that task's row of the block's endpoint, or null),
 * its own `strings`, `now`, and where it is: `area` (inline, panel or menu) and
 * `width` (base … xl). Besides the plug-in template vocabulary it places the
 * contract's block elements, each a `<button>` or `<menu-item>` naming one of
 * the block's declared actions, as written.
 *
 * The one compile both sides run: the server when a plug-in is published, and
 * the browser before it draws a block.
 *
 * Kept free of the browser and of `@/` imports: the server runs it.
 */

import type { CompileResult, ElementDefinition } from "../templates/compile.ts";
import { compileTemplate } from "../templates/compile.ts";
import { BLOCK_ELEMENT_PROPS } from "../templates/vocabulary.ts";
import { camel } from "../widgets/elements.ts";
import { type EndpointReturn, returnFields, stringsShape } from "../widgets/pluginTemplate.ts";

/** The contract's block elements, with the actions this block may name. Each holds its own label. */
const blockElements = (actionKeys: readonly string[]): Record<string, ElementDefinition> => {
  const named: Record<string, readonly string[]> = { action: actionKeys };
  return Object.fromEntries(
    Object.entries(BLOCK_ELEMENT_PROPS).map(([name, props]) => [
      name,
      {
        props: Object.fromEntries(props.map((prop) => [prop, camel(prop)])),
        holds: true,
        fixed: Object.fromEntries(
          props.flatMap((prop) => (named[prop] ? [[prop, named[prop]]] : []))
        ),
      },
    ])
  );
};

export const compileBlock = (
  source: string,
  returns: readonly EndpointReturn[],
  stringKeys: readonly string[],
  actionKeys: readonly string[]
): CompileResult =>
  compileTemplate(source, {
    name: "plug-in block",
    section: { data: { task: "TaskListRead" }, parts: {} },
    scope: {
      answer: returnFields(returns, true),
      strings: stringsShape(stringKeys),
      now: "number",
      area: "string",
      width: "string",
    },
    elements: blockElements(actionKeys),
    plugin: true,
  });
