import { Link } from "@tanstack/react-router";

import type { ContactRead } from "@/api/generated/initiativeAPI.schemas";
import { FavoriteToggle } from "@/components/contacts/FavoriteToggle";
import { type ChipGuild, SharedGuildChip } from "@/components/contacts/SharedGuildChip";
import { UserHandle } from "@/components/UserHandle";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { getUrlHandle, getUserDisplayName } from "@/lib/userDisplay";

interface ContactRowProps {
  contact: ContactRead;
  starred: boolean;
  onToggleFavorite: (contact: ContactRead) => void;
  /** The section's guild, dropped from the chip. Omitted in Favorites. */
  omitGuildId?: number;
  guilds: Map<number, ChipGuild>;
}

/**
 * One person, wherever they are listed.
 *
 * The same row in Favorites and under a community, so somebody looks the same
 * in both places and the only difference is which guild the chip drops. The
 * whole row is the link to their profile; the star sits outside it.
 */
export const ContactRow = ({
  contact,
  starred,
  onToggleFavorite,
  omitGuildId,
  guilds,
}: ContactRowProps) => {
  const name = getUserDisplayName(contact);

  return (
    <li className="flex items-center gap-2 rounded-md px-2 hover:bg-muted/50">
      <Link
        to="/u/$handle"
        params={{ handle: getUrlHandle(contact) }}
        className="flex min-w-0 flex-1 items-center gap-3 py-2"
      >
        <ProfileAvatar user={contact} presence={contact.presence} className="size-8" />
        <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-0.5">
          <UserHandle user={contact} className="min-w-0 truncate text-sm" />
          {contact.full_name ? (
            <span className="min-w-0 truncate text-muted-foreground text-xs">
              {contact.full_name}
            </span>
          ) : null}
        </span>
        <SharedGuildChip
          sharedGuildIds={contact.shared_guild_ids}
          omitGuildId={omitGuildId}
          guilds={guilds}
        />
      </Link>
      <FavoriteToggle starred={starred} name={name} onToggle={() => onToggleFavorite(contact)} />
    </li>
  );
};
