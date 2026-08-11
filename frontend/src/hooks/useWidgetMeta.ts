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
