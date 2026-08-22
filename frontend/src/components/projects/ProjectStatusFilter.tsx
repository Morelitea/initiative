import { Archive, LayoutTemplate } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { TOOL_ICONS } from "@/lib/tools";

export const PROJECT_STATUSES = ["active", "templates", "archived"] as const;

export type ProjectStatus = (typeof PROJECT_STATUSES)[number];

export const isProjectStatus = (value: unknown): value is ProjectStatus =>
  typeof value === "string" && (PROJECT_STATUSES as readonly string[]).includes(value);

// Active projects wear the project tool's own icon, from the one registry that
// defines it. Templates deliberately avoid document iconography — that belongs
// to the documents tool.
const STATUS_ICONS = {
  active: TOOL_ICONS[Tool.project],
  templates: LayoutTemplate,
  archived: Archive,
} as const;

type ProjectStatusFilterProps = {
  value: ProjectStatus;
  onChange: (value: ProjectStatus) => void;
  /** Per-state totals; a state whose count hasn't loaded just shows no badge. */
  counts?: Partial<Record<ProjectStatus, number | undefined>>;
};

/**
 * Which projects the list is showing. Active, templates, and archived are three
 * states of one list rather than three destinations, so this is a filter beside
 * the list — not a second row of tabs under the tool tabs. All three stay
 * visible with their totals, so a state advertises itself instead of hiding
 * behind a menu the reader has to open first.
 */
export const ProjectStatusFilter = ({ value, onChange, counts }: ProjectStatusFilterProps) => {
  const { t } = useTranslation("projects");

  return (
    <ToggleGroup
      type="single"
      value={value}
      // Radix clears a single-select group when the active item is clicked
      // again; a list must always be showing one of the three states.
      onValueChange={(next) => next && onChange(next as ProjectStatus)}
      variant="outline"
      aria-label={t("status.label")}
      className="justify-start"
    >
      {PROJECT_STATUSES.map((status) => {
        const Icon = STATUS_ICONS[status];
        const count = counts?.[status];
        return (
          <ToggleGroupItem key={status} value={status} className="gap-2 px-3">
            <Icon className="h-4 w-4" />
            {t(`status.${status}` as const)}
            {typeof count === "number" ? (
              <span className="text-muted-foreground text-xs tabular-nums">{count}</span>
            ) : null}
          </ToggleGroupItem>
        );
      })}
    </ToggleGroup>
  );
};
