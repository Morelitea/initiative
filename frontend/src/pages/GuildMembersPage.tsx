import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import type { PaginationState } from "@tanstack/react-table";
import { UsersRound } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { UserSummary } from "@/api/generated/initiativeAPI.schemas";
import { ContactActionButtons } from "@/components/contacts/ContactActionButtons";
import { ContactActionsMenu } from "@/components/contacts/ContactActionsMenu";
import { FavoriteToggle } from "@/components/contacts/FavoriteToggle";
import { StatusMessage } from "@/components/StatusMessage";
import { UserHandle } from "@/components/UserHandle";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { useAuth } from "@/hooks/useAuth";
import { useFavoriteContacts, useToggleFavoriteContact } from "@/hooks/useContacts";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useDmPermissions } from "@/hooks/useDirectMessages";
import { usePersistedColumnVisibility } from "@/hooks/usePersistedColumnVisibility";
import { USER_SEARCH_PAGE_SIZE, useUserSearch } from "@/hooks/useUsers";
import type { AppColumnDef } from "@/lib/table";
import { getUrlHandle, getUserDisplayName } from "@/lib/userDisplay";

/**
 * Everyone in this community, and a way to reach them.
 *
 * The badge on the community's banner counts people; this is where that count
 * leads. It reads the guild's own roster — the same one every member picker
 * reads — rather than the contacts aggregate, which answers a different
 * question: who this reader may *message*. A page that dropped everybody who
 * takes no messages would be a members page missing members.
 *
 * Each row carries the same actions a person gets anywhere else, and those do
 * still follow what the server says the reader may do. So somebody who takes
 * no messages is listed like anyone else and simply offers nothing to click,
 * which is the honest shape: they are here, and they are not reachable.
 */
/** How long typing settles before the address and the roster follow it. */
const SEARCH_SETTLES_MS = 250;

export const GuildMembersPage = () => {
  const { t } = useTranslation("guilds");
  const { guildId } = useParams({ strict: false }) as { guildId: string };
  const { page = 1, q = "" } = useSearch({ strict: false }) as { page?: number; q?: string };
  const navigate = useNavigate();
  const { user: me } = useAuth();

  const id = Number(guildId);
  const members = useUserSearch({
    search: q || undefined,
    page,
    pageSize: USER_SEARCH_PAGE_SIZE,
    guildIdOverride: id,
  });
  const rows = useMemo(() => members.data?.items ?? [], [members.data]);
  // One question for the whole page. Asked per row, this is a request per row.
  const permissions = useDmPermissions(useMemo(() => rows.map((row) => row.id), [rows]));
  const total = members.data?.total_count ?? 0;
  const pageSize = members.data?.page_size ?? USER_SEARCH_PAGE_SIZE;

  /** Both the search and the page live in the address, so a roster somebody
   *  is halfway through is a link they can send. */
  const setSearch = useCallback(
    (next: Record<string, unknown>) =>
      void navigate({
        to: ".",
        search: (old: Record<string, unknown>) => ({ ...old, ...next }),
        replace: true,
      }),
    [navigate]
  );

  // The field answers every keystroke; the address and the request wait for
  // typing to stop. Committing each letter re-runs the route and asks the
  // server again, which is what made this lag behind the typing.
  const [draft, setDraft] = useState(q);
  const settled = useDebouncedValue(draft, SEARCH_SETTLES_MS);
  // Follow the URL when it changes from outside — back, forward, a shared link.
  useEffect(() => setDraft(q), [q]);
  useEffect(() => {
    // Only once typing has settled *onto the current draft*. Without that, an
    // address changed from outside -- back, forward, a link somebody sent --
    // is immediately overwritten by whatever was being typed 250ms ago, and
    // history cannot be walked.
    if (settled !== draft || settled === q) return;
    // A new search starts at the beginning: page 3 of the old one says nothing
    // about the new one.
    setSearch({ q: settled || undefined, page: undefined });
  }, [settled, draft, q, setSearch]);

  // Starring is a second read: a favourite may be somebody you share no
  // community with, so the list is not a slice of this roster.
  const favorites = useFavoriteContacts("");
  const starred = useMemo(
    () => new Set((favorites.data?.items ?? []).map((contact) => contact.id)),
    [favorites.data]
  );
  const setFavorite = useToggleFavoriteContact();

  const answers = permissions.data?.permissions ?? {};

  const [columnVisibility, setColumnVisibility] = usePersistedColumnVisibility(
    "guild-members-columns",
    []
  );

  const columns = useMemo<AppColumnDef<UserSummary>[]>(
    () => [
      {
        id: "person",
        meta: { label: t("members.person") },
        header: () => <span className="font-medium">{t("members.person")}</span>,
        accessorFn: (row) => row.username,
        cell: ({ row }) => (
          <Link
            to="/u/$handle"
            params={{ handle: getUrlHandle(row.original) }}
            className="flex min-w-0 items-center gap-2 hover:underline"
          >
            <ProfileAvatar
              user={row.original}
              decorations={row.original.profile_decorations}
              className="size-7 shrink-0"
            />
            <UserHandle user={row.original} className="min-w-0" nameClassName="min-w-0 truncate" />
            {/* Only the exception is worn. Badging the other nine rows in ten
                "member" would say nothing and cost the width the actions
                need. */}
            {row.original.guild_role === "admin" ? (
              <Badge variant="secondary" className="shrink-0">
                {t("members.admin")}
              </Badge>
            ) : null}
          </Link>
        ),
      },
      {
        id: "name",
        meta: { label: t("members.name") },
        header: () => <span className="font-medium">{t("members.name")}</span>,
        accessorFn: (row) => row.full_name ?? "",
        cell: ({ row }) => (
          <span className="truncate text-muted-foreground">{row.original.full_name ?? ""}</span>
        ),
      },
      {
        id: "actions",
        meta: { label: t("members.actions") },
        enableSorting: false,
        header: () => <span className="sr-only">{t("members.actions")}</span>,
        cell: ({ row }) => {
          // Your own row carries none of this: starring, ignoring and every
          // way in are refused for yourself, so offering them is offering
          // errors.
          if (row.original.id === me?.id) return null;
          const person = {
            id: row.original.id,
            username: row.original.username,
            discriminator: row.original.discriminator,
          };
          return (
            <div className="flex items-center justify-end gap-1">
              <ContactActionButtons user={person} permission={answers[String(person.id)] ?? null} />
              {/* Its own control rather than a menu item, the way a contacts
                  row has it: starring is one private, reversible click and
                  nothing is told to anybody. */}
              <FavoriteToggle
                starred={starred.has(row.original.id)}
                name={getUserDisplayName(row.original)}
                onToggle={() => setFavorite(row.original.id, starred.has(row.original.id))}
              />
              {/* Everything else a person can be to you — ignoring above all,
                  which a roster is the likeliest place to want. Same menu as
                  their profile and their contacts row, so it holds no surprise
                  and nothing has to be kept in step. */}
              <ContactActionsMenu
                user={person}
                reachOffered
                permission={answers[String(person.id)] ?? null}
              />
            </div>
          );
        },
      },
    ],
    [t, starred, setFavorite, me?.id, answers]
  );

  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <h1 className="font-semibold text-2xl">{t("members.title")}</h1>
        <p className="text-muted-foreground text-sm">{t("memberCount", { count: total })}</p>
      </header>

      {members.isError ? (
        <StatusMessage
          icon={<UsersRound className="size-6" aria-hidden />}
          title={t("members.failed")}
        />
      ) : (
        <DataTable
          columns={columns}
          data={rows}
          // Controlled, because the roster is searched on the server: the
          // table's own filter would only narrow the page already on screen,
          // which is the wrong answer for everybody past the first twenty-five.
          enableFilterInput
          filterInputPlaceholder={t("members.searchPlaceholder")}
          filterValue={draft}
          onFilterValueChange={setDraft}
          enableColumnVisibilityDropdown
          columnVisibility={columnVisibility}
          onColumnVisibilityChange={setColumnVisibility}
          enablePagination
          manualPagination
          pageCount={Math.max(1, Math.ceil(total / pageSize))}
          rowCount={total}
          pageIndex={page - 1}
          onPaginationChange={(next: PaginationState) =>
            setSearch({ page: next.pageIndex + 1 === 1 ? undefined : next.pageIndex + 1 })
          }
          getRowId={(row: UserSummary) => String(row.id)}
        />
      )}
    </div>
  );
};
