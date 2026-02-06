import { useCallback, useMemo, useState } from "react";
import { Check, ChevronDown, Loader2 } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/useAuth";
import type {
  DocumentPermissionLevel,
  DocumentSummary,
  Initiative,
  InitiativeMember,
} from "@/types/api";

interface BulkEditAccessDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  documents: DocumentSummary[];
  onSuccess: () => void;
}

interface SelectableUser {
  id: number;
  name: string;
  email: string;
}

export function BulkEditAccessDialog({
  open,
  onOpenChange,
  documents,
  onSuccess,
}: BulkEditAccessDialogProps) {
  const queryClient = useQueryClient();
  const { user: currentUser } = useAuth();
  const [mode, setMode] = useState<"grant" | "revoke">("grant");
  const [selectedUserIds, setSelectedUserIds] = useState<Set<number>>(new Set());
  const [level, setLevel] = useState<DocumentPermissionLevel>("read");
  const [isPending, setIsPending] = useState(false);
  const [userPickerOpen, setUserPickerOpen] = useState(false);
  const [userSearch, setUserSearch] = useState("");

  // Gather unique initiative IDs from selected documents
  const initiativeIds = useMemo(() => {
    const ids = new Set<number>();
    for (const doc of documents) {
      if (doc.initiative_id) ids.add(doc.initiative_id);
    }
    return [...ids];
  }, [documents]);

  // Fetch initiative data to get member lists
  const { data: initiatives = [] } = useQuery<Initiative[]>({
    queryKey: ["initiatives"],
    queryFn: async () => {
      const response = await apiClient.get<Initiative[]>("/initiatives/");
      return response.data;
    },
    enabled: open,
  });

  // Build list of users from initiatives the selected documents belong to
  const availableUsers = useMemo(() => {
    const userMap = new Map<number, SelectableUser>();
    const relevantInitiatives = initiatives.filter((i) => initiativeIds.includes(i.id));
    for (const initiative of relevantInitiatives) {
      for (const member of initiative.members) {
        if (member.user.id !== currentUser?.id && !userMap.has(member.user.id)) {
          userMap.set(member.user.id, {
            id: member.user.id,
            name: member.user.full_name || member.user.email,
            email: member.user.email,
          });
        }
      }
    }
    return Array.from(userMap.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [initiatives, initiativeIds, currentUser]);

  // Users who have non-owner access on at least one selected document (for revoke)
  const revocableUsers = useMemo(() => {
    const userMap = new Map<number, SelectableUser>();
    for (const doc of documents) {
      for (const perm of doc.permissions ?? []) {
        if (
          perm.level !== "owner" &&
          perm.user_id !== currentUser?.id &&
          !userMap.has(perm.user_id)
        ) {
          // Try to find user info from initiative members
          const initiative = doc.initiative;
          const member = initiative?.members?.find(
            (m: InitiativeMember) => m.user.id === perm.user_id
          );
          userMap.set(perm.user_id, {
            id: perm.user_id,
            name: member?.user?.full_name || member?.user?.email || `User ${perm.user_id}`,
            email: member?.user?.email || "",
          });
        }
      }
    }
    return Array.from(userMap.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [documents, currentUser]);

  const displayUsers = mode === "grant" ? availableUsers : revocableUsers;

  const filteredUsers = useMemo(() => {
    if (!userSearch.trim()) return displayUsers;
    const searchLower = userSearch.toLowerCase();
    return displayUsers.filter(
      (u) =>
        u.name.toLowerCase().includes(searchLower) || u.email.toLowerCase().includes(searchLower)
    );
  }, [displayUsers, userSearch]);

  const toggleUser = useCallback((userId: number) => {
    setSelectedUserIds((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) {
        next.delete(userId);
      } else {
        next.add(userId);
      }
      return next;
    });
  }, []);

  const resetState = useCallback(() => {
    setSelectedUserIds(new Set());
    setLevel("read");
    setMode("grant");
    setUserSearch("");
    setUserPickerOpen(false);
  }, []);

  const handleOpenChange = useCallback(
    (value: boolean) => {
      if (!value) {
        resetState();
      }
      onOpenChange(value);
    },
    [onOpenChange, resetState]
  );

  const handleApply = useCallback(async () => {
    if (selectedUserIds.size === 0) return;

    setIsPending(true);
    try {
      const userIds = [...selectedUserIds];

      if (mode === "grant") {
        await Promise.all(
          documents.map((doc) =>
            apiClient.post(`/documents/${doc.id}/members/bulk`, {
              user_ids: userIds,
              level,
            })
          )
        );
        const count = documents.length;
        toast.success(`Access granted on ${count} document${count === 1 ? "" : "s"}`);
      } else {
        await Promise.all(
          documents.map((doc) =>
            apiClient.post(`/documents/${doc.id}/members/bulk-delete`, {
              user_ids: userIds,
            })
          )
        );
        const count = documents.length;
        toast.success(`Access revoked on ${count} document${count === 1 ? "" : "s"}`);
      }

      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      resetState();
      onOpenChange(false);
      onSuccess();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to update access right now.";
      toast.error(message);
    } finally {
      setIsPending(false);
    }
  }, [selectedUserIds, mode, documents, level, queryClient, resetState, onOpenChange, onSuccess]);

  const selectedCount = selectedUserIds.size;
  const canApply = selectedCount > 0;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Edit Access</DialogTitle>
          <DialogDescription>
            {mode === "grant" ? "Grant" : "Revoke"} access {mode === "grant" ? "on" : "from"}{" "}
            {documents.length} selected document{documents.length === 1 ? "" : "s"}.
          </DialogDescription>
        </DialogHeader>

        <Tabs
          value={mode}
          onValueChange={(v) => {
            setMode(v as "grant" | "revoke");
            setSelectedUserIds(new Set());
            setUserSearch("");
            setUserPickerOpen(false);
          }}
        >
          <TabsList className="w-full">
            <TabsTrigger value="grant" className="flex-1">
              Grant Access
            </TabsTrigger>
            <TabsTrigger value="revoke" className="flex-1">
              Revoke Access
            </TabsTrigger>
          </TabsList>

          <TabsContent value="grant" className="mt-4 space-y-3">
            <div className="space-y-2">
              <label className="text-sm font-medium">Users</label>
              <UserMultiPicker
                users={filteredUsers}
                selectedIds={selectedUserIds}
                onToggle={toggleUser}
                open={userPickerOpen}
                onOpenChange={setUserPickerOpen}
                search={userSearch}
                onSearchChange={setUserSearch}
                placeholder="Select users..."
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Permission level</label>
              <Select value={level} onValueChange={(v) => setLevel(v as DocumentPermissionLevel)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="read">Can view</SelectItem>
                  <SelectItem value="write">Can edit</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </TabsContent>

          <TabsContent value="revoke" className="mt-4 space-y-3">
            {revocableUsers.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                No non-owner permissions on the selected documents.
              </p>
            ) : (
              <div className="space-y-2">
                <label className="text-sm font-medium">Users to revoke</label>
                <UserMultiPicker
                  users={filteredUsers}
                  selectedIds={selectedUserIds}
                  onToggle={toggleUser}
                  open={userPickerOpen}
                  onOpenChange={setUserPickerOpen}
                  search={userSearch}
                  onSearchChange={setUserSearch}
                  placeholder="Select users to revoke..."
                />
              </div>
            )}
          </TabsContent>
        </Tabs>

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <Button
            onClick={() => void handleApply()}
            disabled={isPending || !canApply}
            variant={mode === "revoke" ? "destructive" : "default"}
          >
            {isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Applying…
              </>
            ) : mode === "grant" ? (
              `Grant to ${selectedCount} user${selectedCount === 1 ? "" : "s"}`
            ) : (
              `Revoke from ${selectedCount} user${selectedCount === 1 ? "" : "s"}`
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// Reusable multi-select user picker
function UserMultiPicker({
  users,
  selectedIds,
  onToggle,
  open,
  onOpenChange,
  search,
  onSearchChange,
  placeholder,
}: {
  users: SelectableUser[];
  selectedIds: Set<number>;
  onToggle: (id: number) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  search: string;
  onSearchChange: (value: string) => void;
  placeholder: string;
}) {
  const selectedCount = selectedIds.size;

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <button
          type="button"
          role="combobox"
          aria-expanded={open}
          className={cn(
            "border-input ring-offset-background focus:ring-ring flex h-9 w-full items-center justify-between rounded-md border bg-transparent px-3 py-2 text-sm shadow-sm focus:ring-1 focus:outline-none",
            selectedCount === 0 && "text-muted-foreground"
          )}
        >
          <span className="truncate">
            {selectedCount === 0
              ? placeholder
              : `${selectedCount} user${selectedCount === 1 ? "" : "s"} selected`}
          </span>
          <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput
            placeholder="Search users..."
            value={search}
            onValueChange={onSearchChange}
          />
          <CommandList>
            <CommandGroup>
              {users.length === 0 ? (
                <div className="text-muted-foreground py-6 text-center text-sm">
                  No users found.
                </div>
              ) : (
                users.map((user) => {
                  const isSelected = selectedIds.has(user.id);
                  return (
                    <CommandItem
                      key={user.id}
                      value={`user-${user.id}`}
                      onSelect={() => onToggle(user.id)}
                      className="cursor-pointer"
                    >
                      <div
                        className={cn(
                          "border-primary mr-2 flex h-4 w-4 items-center justify-center rounded-sm border",
                          isSelected
                            ? "bg-primary text-primary-foreground"
                            : "opacity-50 [&_svg]:invisible"
                        )}
                      >
                        <Check className="h-3 w-3" />
                      </div>
                      <div className="flex flex-col">
                        <span className="truncate text-sm">{user.name}</span>
                        {user.name !== user.email && (
                          <span className="text-muted-foreground truncate text-xs">
                            {user.email}
                          </span>
                        )}
                      </div>
                    </CommandItem>
                  );
                })
              )}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
