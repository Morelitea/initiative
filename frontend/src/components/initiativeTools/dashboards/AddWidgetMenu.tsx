/**
 * The widget palette.
 *
 * Every entry comes from the served catalog — presets first (they are the
 * ready-made ones: "Bar chart"), then the bare primitives — so the palette can
 * only offer what the backend validator would accept, and a new widget appears
 * here without a frontend edit. Names come from each widget module's own `meta`,
 * which is what lets an installed listing's widget sit in this list under its
 * author's name.
 */

import { Plus } from "lucide-react";
import { useTranslation as useI18n, useTranslation } from "react-i18next";

import type { WidgetCatalog } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useWidgetMeta } from "@/hooks/useWidgetMeta";
import { MAX_WIDGETS } from "@/lib/widgets/definition";
import { localized } from "@/lib/widgets/widgetMeta";

export interface AddWidgetMenuProps {
  catalog: WidgetCatalog | undefined;
  widgetCount: number;
  /** `typeOrPreset` is resolved against the catalog's presets by the caller. */
  onAdd: (typeOrPreset: string, source: string) => void;
}

export function AddWidgetMenu({ catalog, widgetCount, onAdd }: AddWidgetMenuProps) {
  const { t } = useTranslation("dashboards");
  const atCap = widgetCount >= MAX_WIDGETS;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="sm" disabled={atCap || !catalog}>
          <Plus className="mr-1.5 h-4 w-4" />
          {t("canvas.addWidget")}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-96 w-56 overflow-y-auto">
        {atCap && (
          <DropdownMenuLabel className="font-normal text-muted-foreground text-xs">
            {t("canvas.widgetCap", { max: MAX_WIDGETS })}
          </DropdownMenuLabel>
        )}

        {!!catalog?.presets.length && (
          <>
            <DropdownMenuLabel>{t("canvas.presets")}</DropdownMenuLabel>
            {catalog.presets.map((preset) => (
              <PaletteEntry
                key={preset.name}
                type={preset.primitive}
                presetOptions={preset.options}
                catalog={catalog}
                onAdd={(source) => onAdd(preset.name, source)}
              />
            ))}
            <DropdownMenuSeparator />
          </>
        )}

        <DropdownMenuLabel>{t("canvas.widgets")}</DropdownMenuLabel>
        {(catalog?.widgets ?? []).map((entry) => (
          <PaletteEntry
            key={entry.type}
            type={entry.type}
            catalog={catalog}
            onAdd={(source) => onAdd(entry.type, source)}
          />
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/**
 * One palette row. Adds the widget bound to its first catalog source — a
 * sensible starting point the author then changes in the config dialog, rather
 * than dropping in a widget with nothing to draw.
 *
 * A preset's label is *derived*, not stored: a preset is a primitive plus fixed
 * options, and the widget module already names both. So `bar_chart` reads as
 * "Chart · Bar" in whatever language the widget supports, and a listing that
 * contributes a preset needs no locale entry from us.
 */
function PaletteEntry({
  type,
  presetOptions,
  catalog,
  onAdd,
}: {
  type: string;
  presetOptions?: Record<string, string>;
  catalog: WidgetCatalog | undefined;
  onAdd: (source: string) => void;
}) {
  const { i18n } = useI18n();
  const { name, meta } = useWidgetMeta(type);
  const entry = catalog?.widgets.find((candidate) => candidate.type === type);
  const firstSource = entry?.sources[0];
  if (!firstSource) return null;

  const qualifiers = Object.entries(presetOptions ?? {})
    .map(([key, value]) => localized(meta?.options?.[key]?.values?.[value], i18n.language))
    .filter(Boolean);

  return (
    <DropdownMenuItem onSelect={() => onAdd(firstSource)}>
      {qualifiers.length ? `${name} · ${qualifiers.join(" · ")}` : name}
    </DropdownMenuItem>
  );
}
