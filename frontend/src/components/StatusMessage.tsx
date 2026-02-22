import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";

import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";

interface StatusMessageProps {
  icon: ReactNode;
  title: string;
  description?: string;
  backTo?: string;
  backLabel?: string;
}

export function StatusMessage({ icon, title, description, backTo, backLabel }: StatusMessageProps) {
  return (
    <Empty>
      <EmptyHeader>
        <EmptyMedia variant="icon">{icon}</EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        {description && <EmptyDescription>{description}</EmptyDescription>}
      </EmptyHeader>
      {backTo && backLabel && (
        <Button variant="link" size="sm" asChild className="px-0">
          <Link to={backTo}>{backLabel}</Link>
        </Button>
      )}
    </Empty>
  );
}
