import type { UserSummary } from "@/api/generated/initiativeAPI.schemas";
import { UserHandle } from "@/components/UserHandle";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { getAvatarSrc, getInitialsForUser, hasDisplayName } from "@/lib/userDisplay";

/**
 * One member found.
 *
 * A person is not a tool, so this is not the tool row with a different icon:
 * it shows the face and the handle, which is what identifies someone. It does
 * not link anywhere yet — there is no page for a person to open — so it reads
 * as a card rather than offering a click that would go nowhere.
 */
export function MemberResultRow({ member }: { member: UserSummary }) {
  return (
    <div className="flex items-center gap-3 rounded-md px-3 py-2">
      <Avatar className="h-8 w-8 shrink-0">
        <AvatarImage src={getAvatarSrc(member)} alt="" />
        <AvatarFallback className="text-xs">{getInitialsForUser(member)}</AvatarFallback>
      </Avatar>
      <div className="min-w-0">
        {hasDisplayName(member) && <div className="truncate font-medium">{member.full_name}</div>}
        <UserHandle
          user={member}
          className={hasDisplayName(member) ? "text-muted-foreground text-sm" : "font-medium"}
        />
      </div>
    </div>
  );
}
