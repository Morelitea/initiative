import { Check, Users, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { getRoleLabel, useRoleLabels } from "@/hooks/useRoleLabels";
import { getInitials } from "@/lib/initials";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { cn } from "@/lib/utils";

interface AssigneeOption {
  id: number;
  label: string;
  avatarUrl?: string | null;
  avatarBase64?: string | null;
}

const resolveAvatarSrc = (option: AssigneeOption): string | undefined =>
  resolveUploadUrl(option.avatarUrl) || option.avatarBase64 || undefined;

interface AssigneeSelectorProps {
  selectedIds: number[];
  options: AssigneeOption[];
  onChange: (ids: number[]) => void;
  disabled?: boolean;
  emptyMessage?: string;
  /** When present and in the option list, this user floats to the top of the
   *  unselected group so people can quickly assign themselves. */
  currentUserId?: number;
}

export const AssigneeSelector = ({
  selectedIds,
  options,
  onChange,
  disabled = false,
  emptyMessage,
  currentUserId,
}: AssigneeSelectorProps) => {
  const { t } = useTranslation("projects");
  const { data: roleLabels } = useRoleLabels();
  const memberLabel = getRoleLabel("member", roleLabels);
  const resolvedEmptyMessage = emptyMessage ?? t("assignee.emptyMessage", { memberLabel });
  const [open, setOpen] = useState(false);

  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);

  const optionById = useMemo(() => {
    const map = new Map<number, AssigneeOption>();
    options.forEach((option) => {
      map.set(option.id, option);
    });
    return map;
  }, [options]);

  // Ordering: selected assignees first, then the current user, then everyone
  // else. Each bucket keeps the incoming option order.
  const orderedOptions = useMemo(() => {
    const selected: AssigneeOption[] = [];
    const currentUser: AssigneeOption[] = [];
    const rest: AssigneeOption[] = [];
    options.forEach((option) => {
      if (selectedSet.has(option.id)) {
        selected.push(option);
      } else if (option.id === currentUserId) {
        currentUser.push(option);
      } else {
        rest.push(option);
      }
    });
    return [...selected, ...currentUser, ...rest];
  }, [options, selectedSet, currentUserId]);

  const selectedOptions = useMemo<AssigneeOption[]>(() => {
    return selectedIds.map((id) => {
      const option = optionById.get(id);
      return {
        id,
        label: option?.label ?? `User #${id}`,
        avatarUrl: option?.avatarUrl,
        avatarBase64: option?.avatarBase64,
      };
    });
  }, [optionById, selectedIds]);

  const toggleAssignee = (id: number) => {
    if (!Number.isFinite(id)) {
      return;
    }
    if (selectedSet.has(id)) {
      onChange(selectedIds.filter((value) => value !== id));
    } else {
      onChange([...selectedIds, id]);
    }
  };

  const removeAssignee = (id: number) => {
    onChange(selectedIds.filter((value) => value !== id));
  };

  if (options.length === 0) {
    return <p className="text-muted-foreground text-sm">{resolvedEmptyMessage}</p>;
  }

  return (
    <div className="space-y-3">
      <Popover open={open} onOpenChange={(next) => !disabled && setOpen(next)}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={open}
            disabled={disabled}
            className={cn(
              "h-auto min-h-10 w-full justify-start",
              selectedOptions.length === 0 && "text-muted-foreground"
            )}
          >
            <Users className="mr-2 h-4 w-4 shrink-0 opacity-50" />
            {selectedOptions.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {selectedOptions.map((option) => {
                  const avatarSrc = resolveAvatarSrc(option);
                  return (
                    <span
                      key={option.id}
                      className="inline-flex max-w-full items-center gap-1 rounded-md bg-secondary py-0.5 pr-1.5 pl-1 font-medium text-secondary-foreground text-xs"
                    >
                      <Avatar className="h-4 w-4 border text-[8px]">
                        {avatarSrc ? <AvatarImage src={avatarSrc} alt={option.label} /> : null}
                        <AvatarFallback userId={option.id}>
                          {getInitials(option.label)}
                        </AvatarFallback>
                      </Avatar>
                      <span className="truncate">{option.label}</span>
                      <button
                        type="button"
                        className="ml-0.5 rounded-sm hover:opacity-70 focus:outline-none"
                        aria-label={t("assignee.removeAssignee", { name: option.label })}
                        onClick={(event) => {
                          event.stopPropagation();
                          event.preventDefault();
                          if (!disabled) {
                            removeAssignee(option.id);
                          }
                        }}
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  );
                })}
              </div>
            ) : (
              <span>{t("assignee.searchPlaceholder", { memberLabel })}</span>
            )}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-72 p-0" align="start">
          <Command>
            <CommandInput placeholder={t("assignee.searchPlaceholder", { memberLabel })} />
            <CommandList>
              <CommandEmpty>{resolvedEmptyMessage}</CommandEmpty>
              <CommandGroup>
                {orderedOptions.map((option) => {
                  const isSelected = selectedSet.has(option.id);
                  const isCurrentUser = option.id === currentUserId;
                  const avatarSrc = resolveAvatarSrc(option);
                  return (
                    <CommandItem
                      key={option.id}
                      value={`${option.id}-${option.label}`}
                      onSelect={() => toggleAssignee(option.id)}
                      className="cursor-pointer"
                    >
                      <div
                        className={cn(
                          "mr-2 flex h-4 w-4 shrink-0 items-center justify-center rounded-sm border border-primary",
                          isSelected
                            ? "bg-primary text-primary-foreground"
                            : "opacity-50 [&_svg]:invisible"
                        )}
                      >
                        <Check className="h-3 w-3" />
                      </div>
                      <Avatar className="mr-2 h-6 w-6 border text-[10px]">
                        {avatarSrc ? <AvatarImage src={avatarSrc} alt={option.label} /> : null}
                        <AvatarFallback userId={option.id}>
                          {getInitials(option.label)}
                        </AvatarFallback>
                      </Avatar>
                      <span className="truncate">{option.label}</span>
                      {isCurrentUser ? (
                        <span className="ml-2 text-muted-foreground text-xs">
                          {t("assignee.you")}
                        </span>
                      ) : null}
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
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
