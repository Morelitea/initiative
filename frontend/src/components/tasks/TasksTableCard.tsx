import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";

type TasksTableCardProps = {
  title: string;
  description?: string;
  isEmpty: boolean;
  emptyMessage?: string;
  children: ReactNode;
  contentClassName?: string;
};

export const TasksTableCard = ({
  title,
  description,
  isEmpty,
  emptyMessage = "No tasks yet.",
  children,
  contentClassName,
}: TasksTableCardProps) => (
  <Card className="shadow-sm">
    <CardHeader>
      <CardTitle>{title}</CardTitle>
      {description ? <CardDescription>{description}</CardDescription> : null}
    </CardHeader>
    <CardContent className={cn("overflow-x-auto", contentClassName)}>
      {isEmpty ? <p className="text-sm text-muted-foreground">{emptyMessage}</p> : children}
    </CardContent>
  </Card>
);
