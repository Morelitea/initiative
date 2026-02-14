import { useMemo, useState } from "react";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { useRoleLabels, getRoleLabel } from "@/hooks/useRoleLabels";

interface AssigneeOption {
  id: number;
  label: string;
}

interface AssigneeSelectorProps {
  selectedIds: number[];
  options: AssigneeOption[];
  onChange: (ids: number[]) => void;
  disabled?: boolean;
  emptyMessage?: string;
}

export const AssigneeSelector = ({
  selectedIds,
  options,
  onChange,
  disabled = false,
  emptyMessage,
}: AssigneeSelectorProps) => {
  const { t } = useTranslation("projects");
  const { data: roleLabels } = useRoleLabels();
  const memberLabel = getRoleLabel("member", roleLabels);
  const resolvedEmptyMessage = emptyMessage ?? t("assignee.emptyMessage", { memberLabel });
  const [searchValue, setSearchValue] = useState("");

  const labelById = useMemo(() => {
    const map = new Map<number, string>();
    options.forEach((option) => {
      map.set(option.id, option.label);
    });
    return map;
  }, [options]);

  const comboboxItems = useMemo(
    () => options.map((option) => ({ value: String(option.id), label: option.label })),
    [options]
  );

  const selectedOptions = useMemo(() => {
    return selectedIds.map((id) => ({
      id,
      label: labelById.get(id) ?? `User #${id}`,
    }));
  }, [labelById, selectedIds]);

  const addAssignee = (id: number) => {
    if (!Number.isFinite(id) || selectedIds.includes(id)) {
      return;
    }
    onChange([...selectedIds, id]);
  };

  const removeAssignee = (id: number) => {
    onChange(selectedIds.filter((value) => value !== id));
  };

  return (
    <div className="space-y-3">
      {options.length === 0 ? (
        <p className="text-muted-foreground text-sm">{resolvedEmptyMessage}</p>
      ) : (
        <SearchableCombobox
          items={comboboxItems}
          value={searchValue}
          onValueChange={(value) => {
            if (!value) {
              setSearchValue("");
              return;
            }
            const id = Number(value);
            setSearchValue("");
            addAssignee(id);
          }}
          placeholder={t("assignee.searchPlaceholder", { memberLabel })}
          emptyMessage={resolvedEmptyMessage}
          disabled={disabled}
        />
      )}
      <div className="space-y-2 rounded-md border p-3">
        {selectedOptions.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("assignee.noAssignees")}</p>
        ) : (
          <ul className="space-y-2">
            {selectedOptions.map((option) => (
              <li key={option.id} className="flex items-center justify-between gap-3 text-sm">
                <span className="truncate">{option.label}</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  onClick={() => removeAssignee(option.id)}
                  disabled={disabled}
                >
                  <span className="sr-only">
                    {t("assignee.removeAssignee", { name: option.label })}
                  </span>
                  <X className="h-4 w-4" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {selectedIds.length > 0 ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => onChange([])}
          disabled={disabled}
        >
          {t("assignee.clearAssignees")}
        </Button>
      ) : null}
    </div>
  );
};
