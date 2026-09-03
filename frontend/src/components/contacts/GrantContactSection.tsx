import type { ReactNode } from "react";
import { useState } from "react";

import type { ContactGrantRead, ContactRead } from "@/api/generated/initiativeAPI.schemas";
import { ContactSection } from "@/components/contacts/ContactSection";
import type { ChipGuild } from "@/components/contacts/SharedGuildChip";
import { CONTACTS_PAGE_SIZE } from "@/hooks/useContacts";

/**
 * A grant, as a row of this page.
 *
 * No ``full_name``: a real name is a per-community disclosure, and a grant may
 * name somebody the reader shares no community with — which is the whole point
 * of listing them here. No shared communities either, for the same reason: the
 * chip answers "where else do we meet", and this section is for people the
 * answer may be nowhere for.
 */
export const grantAsContact = (grant: ContactGrantRead): ContactRead => ({
  id: grant.user_id,
  username: grant.username,
  discriminator: grant.discriminator,
  full_name: null,
  avatar_url: grant.avatar_url,
  status: grant.status,
  presence: grant.presence,
  shared_guild_ids: [],
});

interface GrantContactSectionProps {
  value: string;
  label: string;
  title: ReactNode;
  items: ContactGrantRead[];
  starredIds: Set<number>;
  onToggleFavorite: (contact: ContactRead) => void;
  guilds: Map<number, ChipGuild>;
  emptyLabel: string;
}

/**
 * People the reader can reach because the two of them agreed to it, rather
 * than because they share a community.
 *
 * Paged here rather than at the server: these lists arrive whole, being small
 * and standing outside the walk that pages the community sections.
 */
export const GrantContactSection = ({
  value,
  label,
  title,
  items,
  starredIds,
  onToggleFavorite,
  guilds,
  emptyLabel,
}: GrantContactSectionProps) => {
  const [page, setPage] = useState(1);

  // Removing the last row of the last page leaves the reader on a page that no
  // longer exists, so the page shown is clamped rather than stored.
  const lastPage = Math.max(1, Math.ceil(items.length / CONTACTS_PAGE_SIZE));
  const current = Math.min(page, lastPage);
  const start = (current - 1) * CONTACTS_PAGE_SIZE;

  return (
    <ContactSection
      value={value}
      label={label}
      title={title}
      items={items.slice(start, start + CONTACTS_PAGE_SIZE).map(grantAsContact)}
      starredIds={starredIds}
      onToggleFavorite={onToggleFavorite}
      guilds={guilds}
      emptyLabel={emptyLabel}
      totalCount={items.length}
      page={current}
      pageSize={CONTACTS_PAGE_SIZE}
      onPageChange={setPage}
    />
  );
};
