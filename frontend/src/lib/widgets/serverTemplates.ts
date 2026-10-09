/**
 * The template compiler, as the server runs it.
 *
 * Built by `pnpm build:editor-server` into `dist-editor/templates.js`, and run in
 * the backend's embedded engine (`app/services/template_engine.py`) when a
 * plug-in is published, so a widget or block template that does not compile
 * refuses the plug-in. The browser runs the same compile before it draws one.
 *
 * Each takes its lists as JSON and answers every problem as JSON: an empty list
 * when the template compiles.
 */

import { compileBlock } from "../blocks/blockTemplate";
import type { CompileResult } from "../templates/compile";
import { compilePluginWidget, type EndpointReturn } from "./pluginTemplate";

const problems = ({ errors }: CompileResult): string =>
  JSON.stringify(errors.map((error) => error.message));

function checkWidget(source: string, returns: string, stringKeys: string): string {
  return problems(
    compilePluginWidget(
      source,
      JSON.parse(returns) as EndpointReturn[],
      JSON.parse(stringKeys) as string[]
    )
  );
}

/** A block's template, with its endpoint's returns, its string keys, its action
 *  keys (each id after `plugin.<public id>.`) and the plug-in's page ids. */
function checkBlock(
  source: string,
  returns: string,
  stringKeys: string,
  actionKeys: string,
  pageIds: string
): string {
  return problems(
    compileBlock(
      source,
      JSON.parse(returns) as EndpointReturn[],
      JSON.parse(stringKeys) as string[],
      JSON.parse(actionKeys) as string[],
      JSON.parse(pageIds) as string[]
    )
  );
}

(globalThis as unknown as { serverTemplates: unknown }).serverTemplates = {
  checkWidget,
  checkBlock,
};
