import type { ReactNode } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

export interface SettingsSectionProps {
  /** What this section is for, in the words the reader would use. */
  title: ReactNode;
  /** One line under the title. Say what the controls do, not that they exist. */
  description?: ReactNode;
  /** A control that belongs to the section as a whole — a link, an add button. */
  action?: ReactNode;
  /** Pinned to the bottom of the card, where a Save button goes. */
  footer?: ReactNode;
  /** Draws the section as a consequence rather than a preference. */
  destructive?: boolean;
  /** Applied to the card, for the rare section that needs to bleed to its edge. */
  className?: string;
  /** Applied to the body, whose default is a comfortable vertical rhythm. */
  contentClassName?: string;
  children: ReactNode;
}

/**
 * One block of settings: a heading, a line of explanation, and the controls.
 *
 * Every settings tab is a stack of these. Having one component decide the
 * heading weight, the gap under the description and where a Save button sits
 * is what keeps nine tabs written by different hands looking like one screen —
 * and it means a new tab starts from the right answer instead of copying
 * whichever neighbour it was pasted from.
 */
export const SettingsSection = ({
  title,
  description,
  action,
  footer,
  destructive,
  className,
  contentClassName,
  children,
}: SettingsSectionProps) => (
  <Card className={cn("shadow-sm", destructive && "border-destructive/50", className)}>
    <CardHeader className={cn(action && "flex-row items-start justify-between gap-4 space-y-0")}>
      <div className="min-w-0 space-y-1.5">
        <CardTitle className={cn(destructive && "text-destructive")}>{title}</CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </CardHeader>
    <CardContent className={cn("space-y-4", contentClassName)}>{children}</CardContent>
    {footer ? <CardFooter className="gap-3 border-t pt-6">{footer}</CardFooter> : null}
  </Card>
);
