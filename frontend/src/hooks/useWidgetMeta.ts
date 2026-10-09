import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { builtinWidget } from "@/lib/widgets/registry";
import { type WidgetMeta, widgetDisplayName } from "@/lib/widgets/widgetMeta";

/**
 * A widget's own metadata, resolved for the viewer's language.
 *
 * Names come from the widget itself, not from `dashboards.json`: a built-in's
 * from its code, a plug-in's from its manifest (`pluginMeta`, which the server
 * checked when the plug-in was published). So an installed listing names
 * itself, and adding a widget needs no locale edit.
 */
export function useWidgetMeta(type: string, pluginMeta?: unknown) {
  const { i18n } = useTranslation();
  const meta = builtinWidget(type)?.meta ?? (pluginMeta as WidgetMeta | undefined) ?? null;
  return {
    meta,
    // Falls back to the type id, so a tile header is never empty.
    name: widgetDisplayName(meta, type, i18n.language),
  };
}

/**
 * The same, for a list of built-in widgets at once: the picker searches over
 * names and option labels, so it needs every widget's metadata before it
 * renders the list.
 */
export function useWidgetMetas(types: string[]): Record<string, WidgetMeta | null> {
  // The list is rebuilt on every render by its caller; keying on the joined ids
  // rather than the array keeps the record stable between renders.
  const key = types.join("\n");
  return useMemo(
    () =>
      Object.fromEntries(
        (key ? key.split("\n") : []).map((type) => [type, builtinWidget(type)?.meta ?? null])
      ),
    [key]
  );
}
