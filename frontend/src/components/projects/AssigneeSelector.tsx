import { Checkbox } from "../ui/checkbox";
import { Button } from "../ui/button";

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
  emptyMessage = "Invite initiative members to assign tasks.",
}: AssigneeSelectorProps) => {
  const toggleId = (id: number, checked: boolean) => {
    if (checked) {
      const next = Array.from(new Set([...selectedIds, id]));
      onChange(next);
      return;
    }
    onChange(selectedIds.filter((value) => value !== id));
  };

  return (
    <div className="space-y-3">
      <div className="space-y-2 rounded-md border p-3">
        {options.length === 0 ? (
          <p className="text-sm text-muted-foreground">{emptyMessage}</p>
        ) : (
          <ul className="space-y-2">
            {options.map((option) => (
              <li key={option.id}>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={selectedIds.includes(option.id)}
                    onCheckedChange={(next) => toggleId(option.id, Boolean(next))}
                    disabled={disabled}
                  />
                  <span>{option.label}</span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </div>
      {selectedIds.length > 0 ? (
        <Button type="button" variant="ghost" size="sm" onClick={() => onChange([])} disabled={disabled}>
          Clear assignees
        </Button>
      ) : null}
    </div>
  );
};
