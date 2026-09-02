import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ContactGuildSection, ContactRead } from "@/api/generated/initiativeAPI.schemas";
import { ContactSection } from "@/components/contacts/ContactSection";
import type { ChipGuild } from "@/components/contacts/SharedGuildChip";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  CONTACTS_PAGE_SIZE,
  useContactSectionPage,
  usePrefetchContactSectionPage,
} from "@/hooks/useContacts";
import { getInitials } from "@/lib/initials";

interface GuildContactSectionProps {
  /** Page one, out of the page-wide aggregate. */
  section: ContactGuildSection;
  /** The term these pages are being read under. */
  search: string;
  starredIds: Set<number>;
  onToggleFavorite: (contact: ContactRead) => void;
  guilds: Map<number, ChipGuild>;
}

/**
 * One community's roster.
 *
 * It owns which page of itself it is showing, so paging one community leaves
 * the others where they were. Page one is already in hand from the aggregate;
 * anything past it is a request for this community alone.
 *
 * The page above remounts these on a new term, which is what resets them to
 * page one — under a different term they are a different set of people.
 */
export const GuildContactSection = ({
  section,
  search,
  starredIds,
  onToggleFavorite,
  guilds,
}: GuildContactSectionProps) => {
  const { t } = useTranslation("contacts");
  const [page, setPage] = useState(1);
  const query = useContactSectionPage(section.guild_id, page, search);
  const prefetch = usePrefetchContactSectionPage();

  const loaded = page === 1 ? section : query.data?.sections?.[0];
  const isLoadingPage = page > 1 && !query.isError && (query.isPending || query.isPlaceholderData);
  const hasPageError = page > 1 && query.isError;

  return (
    <ContactSection
      value={`guild-${section.guild_id}`}
      label={section.guild_name}
      title={
        <>
          <Avatar className="size-5 rounded-md">
            {section.icon_url ? <AvatarImage src={section.icon_url} alt="" /> : null}
            <AvatarFallback className="rounded-md bg-muted text-[0.6rem] text-muted-foreground">
              {getInitials(section.guild_name, "G")}
            </AvatarFallback>
          </Avatar>
          <span className="min-w-0 truncate">{section.guild_name}</span>
        </>
      }
      items={loaded?.items ?? []}
      starredIds={starredIds}
      onToggleFavorite={onToggleFavorite}
      omitGuildId={section.guild_id}
      guilds={guilds}
      emptyLabel={search.trim() ? t("noMatches.section") : t("empty.guild")}
      totalCount={section.total_count}
      page={page}
      pageSize={CONTACTS_PAGE_SIZE}
      onPageChange={setPage}
      onPrefetchPage={(next) => prefetch(section.guild_id, next, search)}
      isLoadingPage={isLoadingPage}
      hasPageError={hasPageError}
      onRetryPage={() => void query.refetch()}
    />
  );
};
