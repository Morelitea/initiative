import { Check, ChevronDown, ChevronsUpDown, Loader2, Users, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { UserSummary } from "@/api/generated/initiativeAPI.schemas";
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
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { type MemberSearchScope, useMemberSearch } from "@/hooks/useUsers";
import { getAvatarSrc, getInitialsForUser, getUserDisplayName } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

/** The slim user shape these pickers render (the search endpoints' `UserSummary`). */
export type MemberSummary = Pick<
  UserSummary,
  "id" | "full_name" | "avatar_url" | "avatar_base64" | "status"
>;

/** A member we can render from partial info — a full {@link MemberSummary} from
 *  search, or just an `{ id }` fallback for a selected user we haven't resolved
 *  yet. The display/avatar helpers tolerate the missing fields. */
export type MemberLike = { id: number } & Partial<MemberSummary>;

/** Accumulate display info for users we've seen — from the caller-provided
 *  already-selected set plus every search page — so a selected chip keeps its
 *  name/avatar even after the query changes and the row leaves the results. */
const useSeenMembers = (selectedUsers: MemberLike[] | undefined, results: MemberSummary[]) => {
  const [seen, setSeen] = useState<Map<number, MemberLike>>(() => new Map());
  useEffect(() => {
    setSeen((prev) => {
      const next = new Map(prev);
      let changed = false;
      // Only add ids we haven't seen — the update must be idempotent, or a
      // fresh `selectedUsers`/`results` array identity on every render would
      // loop (setState → render → effect → setState).
      for (const user of [...(selectedUsers ?? []), ...results]) {
        if (!next.has(user.id)) {
          next.set(user.id, user);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [selectedUsers, results]);
  return seen;
};

const MemberAvatar = ({ user, className }: { user: MemberLike; className?: string }) => {
  const src = getAvatarSrc(user);
  const label = getUserDisplayName(user);
  return (
    <Avatar className={cn("h-6 w-6 border text-[10px]", className)}>
      {src ? <AvatarImage src={src} alt={label} /> : null}
      <AvatarFallback userId={user.id}>{getInitialsForUser(user)}</AvatarFallback>
    </Avatar>
  );
};

// ── Multi-select (assignees, linked members) ─────────────────────────────────

interface MemberMultiSelectProps {
  /** Which RLS-scoped roster to search (guild / initiative / project). */
  scope: MemberSearchScope;
  selectedIds: number[];
  onChange: (ids: number[]) => void;
  /** Display info for already-selected users (e.g. a task's `assignees`) so
   *  chips render before/without a search. */
  selectedUsers?: MemberLike[];
  /** Floats the current user to the top of the results for quick self-assign. */
  currentUserId?: number;
  disabled?: boolean;
  placeholder?: string;
  emptyMessage?: string;
  className?: string;
  /**
   * "default" — full editor: avatar chips in the trigger + a "clear" button
   * below (assignee/member editing).
   * "filter" — compact `h-9` trigger matching the sibling filter dropdowns
   * (a summary label, no chips, no clear button).
   */
  variant?: "default" | "filter";
}

export const MemberMultiSelect = ({
  scope,
  selectedIds,
  onChange,
  selectedUsers,
  currentUserId,
  disabled = false,
  placeholder,
  emptyMessage,
  className,
  variant = "default",
}: MemberMultiSelectProps) => {
  const { t } = useTranslation(["projects", "common"]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query, 250);

  const searchResult = useMemberSearch(scope, { search: debounced, enabled: open });
  const results = useMemo<MemberSummary[]>(
    () => searchResult.data?.items ?? [],
    [searchResult.data]
  );
  const seen = useSeenMembers(selectedUsers, results);

  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const resolvedPlaceholder = placeholder ?? t("projects:assignee.searchPlaceholder");
  const resolvedEmpty = emptyMessage ?? t("projects:assignee.emptyMessage");

  // Always surface the currently-selected members, even when the active search
  // doesn't return them — otherwise a selection the server no longer matches
  // (a stale saved filter, or a member who lost access) could never be
  // de-selected from the dropdown. They render checked (resolved via `seen`,
  // falling back to "User #<id>") and toggling removes them. Then current user
  // first, then everyone else (results are already name-sorted).
  const orderedResults = useMemo<MemberLike[]>(() => {
    const resultIds = new Set(results.map((u) => u.id));
    const selectedNotInResults = selectedIds
      .filter((id) => !resultIds.has(id))
      .map((id): MemberLike => seen.get(id) ?? { id });
    const merged: MemberLike[] = [...selectedNotInResults, ...results];
    if (currentUserId == null) return merged;
    const mine = merged.filter((u) => u.id === currentUserId);
    const rest = merged.filter((u) => u.id !== currentUserId);
    return [...mine, ...rest];
  }, [results, selectedIds, seen, currentUserId]);

  const toggle = (id: number) => {
    if (!Number.isFinite(id)) return;
    if (selectedSet.has(id)) {
      onChange(selectedIds.filter((value) => value !== id));
    } else {
      onChange([...selectedIds, id]);
    }
  };

  const remove = (id: number) => onChange(selectedIds.filter((value) => value !== id));

  const handleOpenChange = (next: boolean) => {
    if (disabled) return;
    setOpen(next);
    if (!next) setQuery("");
  };

  // Compact summary for the filter variant: placeholder / the single name /
  // "N selected".
  const filterSummary = useMemo(() => {
    if (selectedIds.length === 0) return resolvedPlaceholder;
    if (selectedIds.length === 1) {
      const only = seen.get(selectedIds[0]);
      return getUserDisplayName(only ?? { id: selectedIds[0] }, `User #${selectedIds[0]}`);
    }
    return t("common:countSelected", { count: selectedIds.length });
  }, [selectedIds, seen, resolvedPlaceholder, t]);

  return (
    <div className={cn(variant === "default" && "space-y-3", className)}>
      <Popover open={disabled ? false : open} onOpenChange={handleOpenChange}>
        <PopoverTrigger asChild>
          {variant === "filter" ? (
            <button
              type="button"
              role="combobox"
              aria-expanded={!disabled && open}
              disabled={disabled}
              className={cn(
                "flex h-9 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm ring-offset-background focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
                selectedIds.length === 0 && "text-muted-foreground"
              )}
            >
              <span className="truncate">{filterSummary}</span>
              <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
            </button>
          ) : (
            <Button
              variant="outline"
              role="combobox"
              aria-expanded={!disabled && open}
              disabled={disabled}
              className={cn(
                "h-auto min-h-10 w-full justify-start",
                selectedIds.length === 0 && "text-muted-foreground"
              )}
            >
              <Users className="h-4 w-4 shrink-0 opacity-50" />
              {selectedIds.length > 0 ? (
                <div className="flex flex-wrap gap-1">
                  {selectedIds.map((id) => {
                    const user = seen.get(id) ?? { id, full_name: null };
                    const label = getUserDisplayName(user, `User #${id}`);
                    return (
                      <span
                        key={id}
                        className="inline-flex max-w-full items-center gap-1 rounded-md bg-secondary py-0.5 pr-1.5 pl-1 font-medium text-secondary-foreground text-xs"
                      >
                        <MemberAvatar user={user} className="h-4 w-4 text-[8px]" />
                        <span className="truncate">{label}</span>
                        <button
                          type="button"
                          className="ml-0.5 rounded-sm hover:opacity-70 focus:outline-none"
                          aria-label={t("projects:assignee.removeAssignee", { name: label })}
                          onClick={(event) => {
                            event.stopPropagation();
                            event.preventDefault();
                            if (!disabled) remove(id);
                          }}
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    );
                  })}
                </div>
              ) : (
                <span>{resolvedPlaceholder}</span>
              )}
            </Button>
          )}
        </PopoverTrigger>
        <PopoverContent className="w-72 p-0" align="start">
          {/* Server-side search — never re-filter client-side. */}
          <Command shouldFilter={false}>
            <CommandInput
              placeholder={resolvedPlaceholder}
              value={query}
              onValueChange={setQuery}
            />
            <CommandList>
              {searchResult.isFetching && results.length === 0 ? (
                <div className="flex items-center justify-center gap-2 py-6 text-muted-foreground text-sm">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("common:loading")}
                </div>
              ) : (
                <>
                  <CommandEmpty>{resolvedEmpty}</CommandEmpty>
                  <CommandGroup>
                    {orderedResults.map((user) => {
                      const isSelected = selectedSet.has(user.id);
                      const isCurrentUser = user.id === currentUserId;
                      return (
                        <CommandItem
                          key={user.id}
                          value={String(user.id)}
                          onSelect={() => toggle(user.id)}
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
                          <MemberAvatar user={user} className="mr-2" />
                          <span className="truncate">{getUserDisplayName(user)}</span>
                          {isCurrentUser ? (
                            <span className="ml-2 text-muted-foreground text-xs">
                              {t("projects:assignee.you")}
                            </span>
                          ) : null}
                        </CommandItem>
                      );
                    })}
                  </CommandGroup>
                </>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      {variant === "default" && selectedIds.length > 0 ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => onChange([])}
          disabled={disabled}
        >
          {t("projects:assignee.clearAssignees")}
        </Button>
      ) : null}
    </div>
  );
};

// ── Single-select (user-reference property, owner reassign) ───────────────────

interface MemberSelectProps {
  scope: MemberSearchScope;
  value: number | null;
  onChange: (id: number | null) => void;
  /** Display info for the current value so the trigger shows a name without a
   *  search round-trip. */
  selectedUser?: MemberLike | null;
  disabled?: boolean;
  placeholder?: string;
  emptyMessage?: string;
  className?: string;
  "aria-label"?: string;
}

export const MemberSelect = ({
  scope,
  value,
  onChange,
  selectedUser,
  disabled = false,
  placeholder,
  emptyMessage,
  className,
  "aria-label": ariaLabel,
}: MemberSelectProps) => {
  const { t } = useTranslation(["common"]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query, 250);

  const searchResult = useMemberSearch(scope, { search: debounced, enabled: open });
  const results = useMemo<MemberSummary[]>(
    () => searchResult.data?.items ?? [],
    [searchResult.data]
  );
  const selectedUsers = useMemo(() => (selectedUser ? [selectedUser] : undefined), [selectedUser]);
  const seen = useSeenMembers(selectedUsers, results);

  const handleOpenChange = (next: boolean) => {
    if (disabled) return;
    setOpen(next);
    if (!next) setQuery("");
  };

  const selected = value != null ? (seen.get(value) ?? selectedUser ?? { id: value }) : null;
  const triggerLabel = selected
    ? getUserDisplayName(selected, `User #${value}`)
    : (placeholder ?? t("common:selectAnOption"));

  return (
    <div className={cn("w-full", className)}>
      <Popover open={disabled ? false : open} onOpenChange={handleOpenChange}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={!disabled && open}
            aria-label={ariaLabel}
            disabled={disabled}
            className={cn("w-full justify-between", !selected && "text-muted-foreground")}
          >
            <span className="flex min-w-0 items-center gap-2">
              {selected ? <MemberAvatar user={selected} className="h-5 w-5 text-[9px]" /> : null}
              <span className="truncate">{triggerLabel}</span>
            </span>
            <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-72 p-0" align="start">
          <Command shouldFilter={false}>
            <CommandInput
              placeholder={placeholder ?? t("common:search")}
              value={query}
              onValueChange={setQuery}
            />
            <CommandList>
              {searchResult.isFetching && results.length === 0 ? (
                <div className="flex items-center justify-center gap-2 py-6 text-muted-foreground text-sm">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("common:loading")}
                </div>
              ) : (
                <>
                  <CommandEmpty>{emptyMessage ?? t("common:noResults")}</CommandEmpty>
                  <CommandGroup>
                    {value != null ? (
                      <CommandItem
                        value="__clear__"
                        onSelect={() => {
                          onChange(null);
                          handleOpenChange(false);
                        }}
                        className="cursor-pointer text-muted-foreground"
                      >
                        <X className="mr-2 h-4 w-4" />
                        {t("common:clear")}
                      </CommandItem>
                    ) : null}
                    {results.map((user) => (
                      <CommandItem
                        key={user.id}
                        value={String(user.id)}
                        onSelect={() => {
                          onChange(user.id);
                          handleOpenChange(false);
                        }}
                        className="cursor-pointer"
                      >
                        <Check
                          className={cn(
                            "mr-2 h-4 w-4 shrink-0",
                            user.id === value ? "opacity-100" : "opacity-0"
                          )}
                        />
                        <MemberAvatar user={user} className="mr-2" />
                        <span className="truncate">{getUserDisplayName(user)}</span>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
};
