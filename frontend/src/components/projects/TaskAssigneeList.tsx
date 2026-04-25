import type { TaskAssigneeSummary, UserPublic } from "@/api/generated/initiativeAPI.schemas";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { getInitialsForUser, getUserDisplayName, isAnonymizedUser } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";
import { resolveUploadUrl } from "@/lib/uploadUrl";

interface TaskAssigneeListProps {
  assignees: (UserPublic | TaskAssigneeSummary)[];
  size?: "sm" | "md";
  className?: string;
}

const sizeStyles = {
  sm: {
    avatar: "h-4 w-4 text-[8px]",
    text: "text-xs",
  },
  md: {
    avatar: "h-8 w-8 text-xs",
    text: "text-sm",
  },
};

export const TaskAssigneeList = ({ assignees, size = "sm", className }: TaskAssigneeListProps) => {
  if (!assignees.length) {
    return null;
  }

  const styles = sizeStyles[size];

  return (
    <div className={cn("text-muted-foreground flex flex-wrap gap-3", className)}>
      {assignees.map((assignee) => {
        const anonymized = isAnonymizedUser(assignee);
        const displayName = getUserDisplayName(assignee);
        // Suppress avatar image and the deterministic colour fallback for
        // anonymized rows — both leak the prior user's identity.
        const avatarSrc = anonymized
          ? undefined
          : resolveUploadUrl(assignee.avatar_url) || assignee.avatar_base64 || undefined;
        const initials = getInitialsForUser(assignee);

        return (
          <div key={assignee.id} className="flex items-center gap-1">
            <Avatar className={cn("border", styles.avatar)}>
              {avatarSrc ? <AvatarImage src={avatarSrc} alt={displayName} /> : null}
              <AvatarFallback userId={anonymized ? null : assignee.id}>{initials}</AvatarFallback>
            </Avatar>
            <span className={cn("font-medium", styles.text)}>{displayName}</span>
          </div>
        );
      })}
    </div>
  );
};
