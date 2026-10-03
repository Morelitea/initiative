import { Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { UserHoverLink } from "@/components/user/UserHoverLink";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useInitiativeRoster, useInitiativeRosterPages } from "@/hooks/useInitiatives";
import { getUserDisplayName } from "@/lib/userDisplay";

/** Faces in the row before it gives way to the count. */
const FACES = 5;

/**
 * The whole roster, searched on the server and read a page at a time as it is
 * scrolled, so an initiative of thousands opens as fast as one of six.
 */
const RosterList = ({ initiativeId, total }: { initiativeId: number; total: number }) => {
  const { t } = useTranslation(["initiatives", "common"]);
  const [search, setSearch] = useState("");
  const debounced = useDebouncedValue(search);
  const roster = useInitiativeRosterPages(initiativeId, debounced, true);
  const members = roster.data?.pages.flatMap((page) => page.items) ?? [];
  const end = useRef<HTMLLIElement>(null);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = roster;

  // The next page when the bottom of the list comes into view.
  useEffect(() => {
    const node = end.current;
    if (!node || !hasNextPage) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry?.isIntersecting && !isFetchingNextPage) void fetchNextPage();
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  return (
    <>
      <div className="space-y-2 border-b p-2">
        <p className="px-1 font-medium text-sm">{t("detail.member", { count: total })}</p>
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={t("common:search")}
          aria-label={t("common:search")}
          className="h-8"
        />
      </div>
      <ul className="max-h-80 overflow-y-auto p-1">
        {members.map((member) => (
          <li key={member.user.id} className="flex items-center gap-2.5 rounded-md px-2 py-1.5">
            <ProfileAvatar user={member.user} className="h-7 w-7" />
            <UserHoverLink user={member.user} className="min-w-0 truncate text-sm">
              {getUserDisplayName(member.user)}
            </UserHoverLink>
            {member.role_display_name ? (
              <span className="ml-auto shrink-0 text-muted-foreground text-xs">
                {member.role_display_name}
              </span>
            ) : null}
          </li>
        ))}
        {roster.isSuccess && members.length === 0 ? (
          <li className="px-2 py-1.5 text-muted-foreground text-sm">{t("common:noResultsDot")}</li>
        ) : null}
        {hasNextPage || roster.isLoading ? (
          <li ref={end} className="flex justify-center py-2 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          </li>
        ) : null}
      </ul>
    </>
  );
};

/**
 * Who is in an initiative, as people rather than a number.
 *
 * A few faces, each pointing at the person behind it the way a name anywhere
 * else does, and the count beside them opening the whole roster. Only the
 * faces are read with the page; the roster waits until it is opened.
 */
export const InitiativeMembersPeek = ({
  initiativeId,
  memberCount,
}: {
  initiativeId: number;
  memberCount: number;
}) => {
  const { t } = useTranslation("initiatives");
  const faces = useInitiativeRoster(initiativeId, { page_size: FACES });
  const members = faces.data?.items ?? [];
  const total = faces.data?.total_count ?? memberCount;

  return (
    <span className="inline-flex items-center gap-2 align-middle">
      {members.length > 0 ? (
        <span className="-space-x-1.5 inline-flex">
          {members.map((member) => (
            <UserHoverLink key={member.user.id} user={member.user} className="rounded-full">
              <ProfileAvatar
                user={member.user}
                className="h-6 w-6 ring-2 ring-background transition-transform hover:z-10 hover:-translate-y-0.5"
              />
            </UserHoverLink>
          ))}
        </span>
      ) : null}
      <Popover>
        <PopoverTrigger className="rounded-sm underline-offset-4 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {t("detail.member", { count: total })}
        </PopoverTrigger>
        {/* Mounted only while open, which is what keeps the roster unread
            until somebody asks for it. */}
        <PopoverContent align="start" className="w-72 p-0">
          <RosterList initiativeId={initiativeId} total={total} />
        </PopoverContent>
      </Popover>
    </span>
  );
};
