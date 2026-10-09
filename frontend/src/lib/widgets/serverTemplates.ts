/**
 * The template compiler, as the server runs it.
 *
 * Built by `pnpm build:editor-server` into `dist-editor/templates.js`, and run in
 * the backend's embedded engine (`app/services/template_engine.py`) when a
 * plug-in is published, so a widget template that does not compile refuses the
 * plug-in. The browser runs the same compile before it draws one.
 */

import { compilePluginWidget, type EndpointReturn } from "./pluginTemplate";

/** Every problem with a plug-in widget's template, as JSON: an empty list when it compiles. */
function checkWidget(source: string, returns: string, stringKeys: string): string {
  const { errors } = compilePluginWidget(
    source,
    JSON.parse(returns) as EndpointReturn[],
    JSON.parse(stringKeys) as string[]
  );
  return JSON.stringify(errors.map((error) => error.message));
}

(globalThis as unknown as { serverTemplates: unknown }).serverTemplates = { checkWidget };
