import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { builtinWidgetSource } from "@/lib/widgets/registry";
import { readWidgetMeta } from "@/lib/widgets/runtime/host";
import { type WidgetMeta, widgetDisplayName } from "@/lib/widgets/widgetMeta";

/**
 * A widget's own metadata, resolved for the viewer's language.
 *
 * Names come from the widget module, not from `dashboards.json` — so an
 * installed listing names itself, and adding a widget needs no locale edit.
 * Reads go through the sandbox once per module and are cached there.
 */
export function useWidgetMeta(type: string, source?: string) {
  const { i18n } = useTranslation();
  const [meta, setMeta] = useState<WidgetMeta | null>(null);
  const moduleSource = source ?? builtinWidgetSource(type);

  useEffect(() => {
    if (!moduleSource) {
      setMeta(null);
      return;
    }
    let cancelled = false;
    readWidgetMeta(moduleSource).then((result) => {
      if (!cancelled) setMeta(result);
    });
    return () => {
      cancelled = true;
    };
  }, [moduleSource]);

  return {
    meta,
    // Falls back to the type id until the read resolves, so a tile header never
    // flashes empty.
    name: widgetDisplayName(meta, type, i18n.language),
  };
}

/**
 * The same, for a whole list of widgets at once.
 *
 * The picker searches over names and option labels, so it needs every widget's
 * metadata *before* it renders the list — a per-row `useWidgetMeta` would leave
 * the names inside the rows, where the filter cannot reach them. Reads are
 * cached per module, so this is one pass on first open and free after.
 */
export function useWidgetMetas(types: string[]): Record<string, WidgetMeta | null> {
  const [metas, setMetas] = useState<Record<string, WidgetMeta | null>>({});
  // The list is rebuilt on every render by its caller; keying the effect on the
  // joined ids rather than the array is what keeps this from re-reading forever.
  const key = types.join("\n");

  useEffect(() => {
    let cancelled = false;
    const wanted = key ? key.split("\n") : [];
    Promise.all(
      wanted.map(async (type) => {
        const source = builtinWidgetSource(type);
        return [type, source ? await readWidgetMeta(source) : null] as const;
      })
    ).then((entries) => {
      if (!cancelled) setMetas(Object.fromEntries(entries));
    });
    return () => {
      cancelled = true;
    };
  }, [key]);

  return metas;
}
