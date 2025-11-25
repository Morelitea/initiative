import type { User } from "@/types/api";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";

interface TaskAssigneeListProps {
  assignees: User[];
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

const getDisplayName = (user: User) => user.full_name?.trim() || user.email;

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
    <div className={cn("flex flex-wrap gap-3 text-muted-foreground", className)}>
      {assignees.map((assignee) => {
        const displayName = getDisplayName(assignee);
        const avatarSrc = assignee.avatar_url || assignee.avatar_base64 || undefined;
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
