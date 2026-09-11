/**
 * Which of a tool's two states the list is showing — live, or archived.
 *
 * Every tool can be archived, so every tool list needs somewhere for the
 * archived ones to be: a row that vanishes from its list with no way to reach
 * it is a row nobody can take back out. This is the two-state form of the
 * project list's own status filter, shaped the same way so the eight lists
 * agree, and shared rather than rewritten per tool.
 *
 * Lives in {@link ToolListToolbar}'s `leading` slot — the scope the list is
 * showing — beside the filter and view controls rather than inside the filter
 * panel, because it changes what the list *is* rather than narrowing it.
 */

import { Archive } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { TOOL_ICONS } from "@/lib/tools";

export const TOOL_ARCHIVE_STATES = ["active", "archived"] as const;

export type ToolArchiveState = (typeof TOOL_ARCHIVE_STATES)[number];

export const isToolArchiveState = (value: unknown): value is ToolArchiveState =>
  typeof value === "string" && (TOOL_ARCHIVE_STATES as readonly string[]).includes(value);

/** What the list endpoint's `archived` parameter should be for this state.
 *  `undefined` rather than `false` for the live list: the default and the
 *  explicit "not archived" mean the same thing to the API, and leaving it off
 *  keeps the query key — and so the cache entry — the one every other caller
 *  already uses. */
export const archivedParam = (state: ToolArchiveState): true | undefined =>
  state === "archived" ? true : undefined;

type ToolArchiveFilterProps = {
  tool: Tool;
  value: ToolArchiveState;
  onChange: (value: ToolArchiveState) => void;
};

export const ToolArchiveFilter = ({ tool, value, onChange }: ToolArchiveFilterProps) => {
  const { t } = useTranslation("common");

  const icons = { active: TOOL_ICONS[tool], archived: Archive } as const;

  return (
    <ToggleGroup
      type="single"
      value={value}
      // Radix clears a single-select group when the active item is clicked
      // again; the list is always showing one of the two.
      onValueChange={(next) => next && onChange(next as ToolArchiveState)}
      variant="outline"
      aria-label={t("toolArchiveFilter.label")}
      className="h-9 shrink-0 justify-start"
    >
      {TOOL_ARCHIVE_STATES.map((state) => {
        const Icon = icons[state];
        return (
          <ToggleGroupItem
            key={state}
            value={state}
            // Below `sm` the label drops and the icon carries it, the way the
            // project status filter does — the row is shared with the filter,
            // view, and overflow controls.
            aria-label={t(`toolArchiveFilter.${state}` as const)}
            className="h-9 shrink-0 gap-1.5 px-2.5 sm:gap-2 sm:px-3"
          >
            <Icon className="h-4 w-4" />
            <span className="hidden sm:inline">{t(`toolArchiveFilter.${state}` as const)}</span>
          </ToggleGroupItem>
        );
      })}
    </ToggleGroup>
  );
};
