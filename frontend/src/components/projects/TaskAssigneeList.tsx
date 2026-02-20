import type { TaskAssigneeSummary, UserPublic } from "@/api/generated/initiativeAPI.schemas";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
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

const getDisplayName = (user: UserPublic | TaskAssigneeSummary) => {
  if (user.full_name?.trim()) {
    return user.full_name.trim();
  }
  // For UserPublic, fall back to email; for TaskAssignee, use a generic label
  if ("email" in user && user.email) {
    return user.email;
  }
  return "User";
};

const getInitials = (value: string) => {
  if (!value) {
    return "?";
  }
  const parts = value.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return value.charAt(0).toUpperCase();
  }
  const initials = parts
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
  return initials || value.charAt(0).toUpperCase();
};

export const TaskAssigneeList = ({ assignees, size = "sm", className }: TaskAssigneeListProps) => {
  if (!assignees.length) {
    return null;
  }

  const styles = sizeStyles[size];

  return (
    <div className={cn("text-muted-foreground flex flex-wrap gap-3", className)}>
      {assignees.map((assignee) => {
        const displayName = getDisplayName(assignee);
        const avatarSrc =
          resolveUploadUrl(assignee.avatar_url) || assignee.avatar_base64 || undefined;
        const initials = getInitials(displayName);

        return (
          <div key={assignee.id} className="flex items-center gap-1">
            <Avatar className={cn("border", styles.avatar)}>
              {avatarSrc ? <AvatarImage src={avatarSrc} alt={displayName} /> : null}
              <AvatarFallback>{initials}</AvatarFallback>
            </Avatar>
            <span className={cn("font-medium", styles.text)}>{displayName}</span>
          </div>
        );
      })}
    </div>
  );
};
