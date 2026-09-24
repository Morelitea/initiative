import { ChevronDown, SlidersHorizontal } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { PropertyDefinitionRead } from "@/api/generated/initiativeAPI.schemas";
import {
  isKanbanFieldVisible,
  type KanbanFieldVisibility,
  kanbanFieldOptions,
} from "@/components/projects/kanbanFields";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface KanbanFieldsMenuProps {
  propertyDefinitions: PropertyDefinitionRead[];
  visibility: KanbanFieldVisibility;
  onChange: (
    updater: KanbanFieldVisibility | ((prev: KanbanFieldVisibility) => KanbanFieldVisibility)
  ) => void;
}

/**
 * The board's answer to the table's "Columns" dropdown, called **Fields**
 * because a board's columns are its statuses and reusing the word here would
 * read as an offer to hide those.
 */
export const KanbanFieldsMenu = ({
  propertyDefinitions,
  visibility,
  onChange,
}: KanbanFieldsMenuProps) => {
  const { t } = useTranslation("projects");
  const options = kanbanFieldOptions(propertyDefinitions, (key) => t(key as never));
  const hiddenCount = options.filter(
    (option) => !isKanbanFieldVisible(visibility, option.id)
  ).length;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm">
          <SlidersHorizontal className="h-4 w-4" />
          {t("kanban.fields.label")}
          {hiddenCount > 0 ? (
            <span className="text-muted-foreground text-xs">
              {t("kanban.fields.hiddenCount", { count: hiddenCount })}
            </span>
          ) : null}
          <ChevronDown className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-[min(70vh,24rem)] w-56 overflow-y-auto">
        <DropdownMenuLabel>{t("kanban.fields.menuTitle")}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {options.map((option) => (
          <DropdownMenuCheckboxItem
            key={option.id}
            checked={isKanbanFieldVisible(visibility, option.id)}
            // The menu stays open so several fields can be turned off in one
            // go — closing after each one would mean reopening it per field.
            onSelect={(event) => event.preventDefault()}
            onCheckedChange={(checked) =>
              onChange((prev) => ({ ...prev, [option.id]: Boolean(checked) }))
            }
          >
            {option.label}
          </DropdownMenuCheckboxItem>
        ))}
        {hiddenCount > 0 ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => onChange({})}>
              {t("kanban.fields.showAll")}
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
