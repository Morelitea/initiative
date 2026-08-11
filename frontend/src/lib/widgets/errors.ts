/**
 * Every way rendering a widget can fail, in one place.
 *
 * Three layers can reject a widget — the runtime that executes it, the
 * validator that checks what it drew, and the tile that couldn't find a module
 * for it — and the viewer sees one error tile regardless. Collecting the codes
 * here gives that tile a single union to localize, and gives
 * `widgetErrors.test.ts` something to check the locale files against, so a new
 * failure mode cannot ship without a message in every language.
 */

import { SandboxErrorCode } from "./runtime/sandbox";
import { SceneErrorCode } from "./validateScene";

export const WidgetErrorCode = {
  ...SandboxErrorCode,
  ...SceneErrorCode,
  /** The definition names a widget type this build has no module for — an
   *  install from a listing built against a newer app. */
  TYPE_UNSUPPORTED: "WIDGET_TYPE_UNSUPPORTED",
} as const;

export type WidgetErrorCode = (typeof WidgetErrorCode)[keyof typeof WidgetErrorCode];

export const WIDGET_ERROR_CODES = Object.values(WidgetErrorCode) as WidgetErrorCode[];
