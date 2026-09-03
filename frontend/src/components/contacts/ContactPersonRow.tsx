import type { ReactNode } from "react";

import type { ProfileDecorationsOutput } from "@/api/generated/initiativeAPI.schemas";
import { UserHandle } from "@/components/UserHandle";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";

interface ContactPersonRowProps {
  /** Decorations travel on the person rather than as a prop of their own, so a
   *  caller that already holds a grant row spreads it and the picture is
   *  dressed. A shape without them — the ignore list — draws a bare one. */
  user: {
    id: number;
    username: string;
    discriminator: number;
    avatar_url?: string | null;
    profile_decorations?: ProfileDecorationsOutput | null;
  };
  /** One line under the handle — when they connected, what they asked for. */
  detail?: ReactNode;
  /** The row's own controls. */
  children?: ReactNode;
}

/**
 * One person in a contacts *ledger* — connections, pending requests, ignored
 * accounts — wherever that ledger is rendered.
 *
 * Distinct from `ContactRow`, which is the directory row on My Contacts: that
 * one sits on the page's shared column template and opens a conversation. This
 * is a list item with buttons, and the two are not the same shape.
 */
export const ContactPersonRow = ({ user, detail, children }: ContactPersonRowProps) => (
  <li className="flex items-center gap-3 py-2">
    <ProfileAvatar user={user} decorations={user.profile_decorations} className="size-8 shrink-0" />
    <div className="min-w-0 flex-1">
      <UserHandle user={user} className="text-sm" nameClassName="min-w-0 truncate" />
      {detail ? <p className="truncate text-muted-foreground text-xs">{detail}</p> : null}
    </div>
    {children ? <div className="flex shrink-0 items-center gap-2">{children}</div> : null}
  </li>
);
