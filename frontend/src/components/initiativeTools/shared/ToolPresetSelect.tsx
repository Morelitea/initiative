import { useTranslation } from "react-i18next";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export type PresetOption = { slug: string; name: string };

/** Radix needs a non-empty value, and "no preset" still has to be showable. */
const CUSTOM = "__custom__";

type ToolPresetSelectProps = {
  presets: readonly PresetOption[];
  /** The preset currently shown, or null when the filters are ad hoc. */
  activeSlug: string | null;
  /** The active preset's values have been tweaked away from what it holds. */
  modified: boolean;
  onSelect: (slug: string) => void;
  label: string;
  /** Shown as the value when no preset is active. */
  customLabel: string;
  modifiedLabel: string;
};

/**
 * Which saved filter set a list is showing — it leads the filter panel's
 * control row, because picking one sets every field below it.
 *
 * Tool-agnostic: it knows about slugs and names, not about tasks.
 */
export const ToolPresetSelect = ({
  presets,
  activeSlug,
  modified,
  onSelect,
  label,
  customLabel,
  modifiedLabel,
}: ToolPresetSelectProps) => {
  const { t } = useTranslation("common");
  const active = presets.find((preset) => preset.slug === activeSlug) ?? null;

  return (
    <Select
      value={activeSlug ?? CUSTOM}
      onValueChange={(value) => value !== CUSTOM && onSelect(value)}
    >
      <SelectTrigger id="preset-select" aria-label={label} className="h-9 w-full sm:w-56">
        {/* The trigger carries the "modified" marker, not the list: the list is
            what a preset IS, and every entry there is unmodified by definition. */}
        <SelectValue placeholder={customLabel}>
          {active ? `${active.name}${modified ? ` · ${modifiedLabel}` : ""}` : customLabel}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {/* Only listed while it is what's showing — "custom" is a state you
            arrive at by editing filters, not one you pick. */}
        {activeSlug === null ? (
          <SelectItem value={CUSTOM} disabled>
            {customLabel}
          </SelectItem>
        ) : null}
        {presets.map((preset) => (
          <SelectItem key={preset.slug} value={preset.slug}>
            {preset.name}
          </SelectItem>
        ))}
        {presets.length === 0 ? (
          <SelectItem value={CUSTOM} disabled>
            {t("noResults")}
          </SelectItem>
        ) : null}
      </SelectContent>
    </Select>
  );
};
