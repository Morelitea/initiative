import { Link } from "@tanstack/react-router";

import type { ContactRead } from "@/api/generated/initiativeAPI.schemas";
import { ContactActionsMenu } from "@/components/contacts/ContactActionsMenu";
import { CONTACT_ROW_GRID, CONTACT_ROW_OUTER } from "@/components/contacts/ContactColumns";
import { FavoriteToggle } from "@/components/contacts/FavoriteToggle";
import { type ChipGuild, SharedGuildChip } from "@/components/contacts/SharedGuildChip";
import { UserHandle } from "@/components/UserHandle";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { getUrlHandle, getUserDisplayName } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

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
 * in both places and the only difference is which guild the chip drops. Its
 * cells sit on the page's shared column template; the link covers all of them
 * and the star sits outside it, in the one column the link does not reach.
 *
 * The link goes to their profile, which is where everything you might do about
 * somebody is gathered -- messaging them among it. Clicking a person to land on
 * the person is what a row of people reads as; the conversation is one button
 * further, and it is there whether or not the channel is already open.
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
    <li className={cn(CONTACT_ROW_OUTER, "rounded-md px-2 hover:bg-muted/50")}>
      <Link
        to="/u/$handle"
        params={{ handle: getUrlHandle(contact) }}
        className={cn(CONTACT_ROW_GRID, "py-1.5")}
      >
        <ProfileAvatar
          user={contact}
          decorations={contact.profile_decorations}
          presence={contact.presence}
          className="size-8"
        />
        <span className="flex min-w-0 text-sm">
          <UserHandle
            user={contact}
            className="min-w-0 max-w-full"
            nameClassName="min-w-0 truncate"
            numberClassName="shrink-0"
          />
        </span>
        <span className="hidden min-w-0 truncate text-muted-foreground text-sm sm:block">
          {contact.full_name ?? ""}
        </span>
        <SharedGuildChip
          sharedGuildIds={contact.shared_guild_ids}
          omitGuildId={omitGuildId}
          guilds={guilds}
        />
      </Link>
      <FavoriteToggle starred={starred} name={name} onToggle={() => onToggleFavorite(contact)} />
      {/* Outside the link, like the star: acting on somebody is not the same
          gesture as going to look at them. */}
      <ContactActionsMenu
        omit={["profile", "favorite"]}
        user={{
          id: contact.id,
          username: contact.username,
          discriminator: contact.discriminator,
        }}
      />
    </li>
  );
};
