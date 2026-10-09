import type { LucideIcon } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export type ViewOption = { slug: string; name: string; icon: LucideIcon };

type ToolViewSelectProps = {
  views: readonly ViewOption[];
  /** The view shown. */
  activeSlug: string | null;
  /** This person's filters differ from the active view's. */
  modified: boolean;
  onSelect: (slug: string) => void;
  label: string;
  modifiedLabel: string;
};

/**
 * Which of a list's views it is showing — each a layout with its own filters,
 * so picking one sets both.
 *
 * Tool-agnostic: it knows about slugs, names and icons, not about tasks.
 */
export const ToolViewSelect = ({
  views,
  activeSlug,
  modified,
  onSelect,
  label,
  modifiedLabel,
}: ToolViewSelectProps) => {
  const active = views.find((view) => view.slug === activeSlug) ?? null;
  const ActiveIcon = active?.icon;

  return (
    <Select value={activeSlug ?? ""} onValueChange={onSelect}>
      <SelectTrigger aria-label={label} className="h-9 w-auto max-w-64 gap-2">
        {/* The trigger carries the "modified" marker, not the list: the list is
            what a view IS, and every entry there is unmodified by definition. */}
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
        {views.map(({ slug, name, icon: Icon }) => (
          <SelectItem key={slug} value={slug}>
            <span className="flex items-center gap-2">
              <Icon className="h-4 w-4 shrink-0" />
              {name}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
};
