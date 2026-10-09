/**
 * Widget-supplied metadata: what a widget calls itself.
 *
 * A widget's name, its description, and the labels for its own options belong
 * to the widget, not to this app's locale files. Putting them here would mean a
 * marketplace widget could not name itself without an app release — and that a
 * second copy of the widget vocabulary sat in `dashboards.json`, drifting from
 * the registry. So a widget carries `meta`, its strings in every language its
 * author supports: a built-in in its code, a plug-in in its manifest, which the
 * server checks when the plug-in is published (`widget_meta.py`).
 *
 * What stays plugin-owned is what is genuinely ours: binding *source* labels (they
 * name our endpoints and are shared by every widget) and page chrome.
 */

/** Language code → text. No locale is required: resolution falls back through
 *  the base language, then English, then whatever the widget did supply, so a
 *  widget that ships one language still renders everywhere. */
export type LocalizedText = Record<string, string>;

export interface WidgetOptionMeta {
  label: LocalizedText;
  /** Label per allowed value. The *values* themselves are the backend's
   *  (`WIDGET_SPECS[...].options`); only how they read is the widget's. */
  values?: Record<string, LocalizedText>;
}

export interface WidgetMeta {
  name: LocalizedText;
  description?: LocalizedText;
  options?: Record<string, WidgetOptionMeta>;
}

// --- resolution ------------------------------------------------------------

/**
 * Pick the best string for a language.
 *
 * `de-AT` → `de-AT`, then `de`, then `en`, then whatever the widget shipped —
 * so a widget that supports one language is still readable to everyone, and one
 * that supports many needs no coordination with us.
 */
export function localized(text: LocalizedText | undefined, language: string): string | undefined {
  if (!text) return undefined;
  const base = language.split("-")[0];
  return text[language] ?? text[base] ?? text.en ?? Object.values(text)[0] ?? undefined;
}

/** A widget's display name, falling back to its type id so a module with no
 *  meta still shows something stable rather than a blank tile header. */
export const widgetDisplayName = (
  meta: WidgetMeta | null | undefined,
  type: string,
  language: string
): string => localized(meta?.name, language) ?? type;
