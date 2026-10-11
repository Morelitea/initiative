import type { LucideIcon } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export type LayoutOption = { slug: string; name: string; icon: LucideIcon };
export type PresetOption = { slug: string; name: string };

type ToolLayoutSelectProps = {
  layouts: readonly LayoutOption[];
  /** The layout shown. */
  activeSlug: string | null;
  /** This person narrows the list on screen. */
  modified: boolean;
  onSelect: (slug: string) => void;
  label: string;
  modifiedLabel: string;
  /** What the layout shown offers to start from, under `presetsLabel`. */
  presets?: readonly PresetOption[];
  presetsLabel?: string;
  onPreset?: (slug: string) => void;
};

/** A preset's value in the menu: apart from every layout's. */
const PRESET = "preset:";

/**
 * Which of a list's layouts it is showing, and the presets that layout offers.
 * Picking a layout shows it; picking a preset applies its filters, and the
 * layout stays.
 *
 * Tool-agnostic: it knows about slugs, names and icons, not about tasks.
 */
export const ToolLayoutSelect = ({
  layouts,
  activeSlug,
  modified,
  onSelect,
  label,
  modifiedLabel,
  presets = [],
  presetsLabel,
  onPreset,
}: ToolLayoutSelectProps) => {
  const active = layouts.find((layout) => layout.slug === activeSlug) ?? null;
  const ActiveIcon = active?.icon;

  return (
    <Select
      value={activeSlug ?? ""}
      onValueChange={(value) =>
        value.startsWith(PRESET) ? onPreset?.(value.slice(PRESET.length)) : onSelect(value)
      }
    >
      <SelectTrigger aria-label={label} className="h-9 w-auto max-w-64 gap-2">
        {/* The trigger carries the "modified" marker, not the list: each
            entry there is a layout or a preset as it is kept. */}
        <SelectValue>
          {active ? (
            <span className="flex min-w-0 items-center gap-2">
              {ActiveIcon ? <ActiveIcon className="h-4 w-4 shrink-0" /> : null}
              <span className="truncate">
                {active.name}
                {modified ? ` · ${modifiedLabel}` : ""}
              </span>
            </span>
          ) : null}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {layouts.map(({ slug, name, icon: Icon }) => (
          <SelectItem key={slug} value={slug}>
            <span className="flex items-center gap-2">
              <Icon className="h-4 w-4 shrink-0" />
              {name}
            </span>
          </SelectItem>
        ))}
        {presets.length > 0 && onPreset ? (
          <>
            <SelectSeparator />
            <SelectGroup>
              <SelectLabel>{presetsLabel}</SelectLabel>
              {presets.map(({ slug, name }) => (
                <SelectItem key={slug} value={`${PRESET}${slug}`}>
                  {name}
                </SelectItem>
              ))}
            </SelectGroup>
          </>
        ) : null}
      </SelectContent>
    </Select>
  );
};
