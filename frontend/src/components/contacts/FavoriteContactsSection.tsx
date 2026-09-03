import { Star } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ContactRead } from "@/api/generated/initiativeAPI.schemas";
import { ContactSection } from "@/components/contacts/ContactSection";
import type { ChipGuild } from "@/components/contacts/SharedGuildChip";
import { CONTACTS_PAGE_SIZE } from "@/hooks/useContacts";

export const FAVORITES_VALUE = "favorites";

interface FavoriteContactsSectionProps {
  /** Everybody starred, in one piece — the server sends no pages here. */
  items: ContactRead[];
  starredIds: Set<number>;
  onToggleFavorite: (contact: ContactRead) => void;
  guilds: Map<number, ChipGuild>;
  searching: boolean;
}

/**
 * The starred section.
 *
 * Paged here rather than at the server, because the starred list arrives whole
 * — a favorite may be somebody the reader shares no community with, so it
 * cannot come from the walk that pages the other sections. Same columns, same
 * pager, so it browses like the rest of the page.
 */
export const FavoriteContactsSection = ({
  items,
  starredIds,
  onToggleFavorite,
  guilds,
  searching,
}: FavoriteContactsSectionProps) => {
  const { t } = useTranslation("contacts");
  const [page, setPage] = useState(1);

  // Unstarring the last row of the last page leaves the reader on a page that
  // no longer exists, so the page shown is clamped rather than stored.
  const lastPage = Math.max(1, Math.ceil(items.length / CONTACTS_PAGE_SIZE));
  const current = Math.min(page, lastPage);
  const start = (current - 1) * CONTACTS_PAGE_SIZE;

  return (
    <ContactSection
      value={FAVORITES_VALUE}
      label={t("favorites")}
      title={
        <>
          <Star className="size-4 text-amber-500" />
          <span>{t("favorites")}</span>
        </>
      }
      items={items.slice(start, start + CONTACTS_PAGE_SIZE)}
      starredIds={starredIds}
      onToggleFavorite={onToggleFavorite}
      guilds={guilds}
      emptyLabel={searching ? t("noMatches.section") : t("empty.favorites")}
      totalCount={items.length}
      page={current}
      pageSize={CONTACTS_PAGE_SIZE}
      onPageChange={setPage}
    />
  );
};
