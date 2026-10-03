/**
 * The tickets the reader filed: where each stands, most recently moved first.
 *
 * Not tasks: a filer follows where their ticket stands and what is said to
 * them, never the task the team works it in. The sidebar offers this page once
 * they have filed something.
 */
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import type { FiledTicketRead } from "@/api/generated/initiativeAPI.schemas";
import { SkeletonRegion } from "@/components/skeletons/PageSkeletons";
import { TicketStateBadge } from "@/components/tickets/TicketStateBadge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import { useFiledTickets } from "@/hooks/useTickets";

const TicketRow = ({ ticket }: { ticket: FiledTicketRead }) => {
  const { t } = useTranslation("intake");
  const moved = useRelativeTime(ticket.updated_at ?? ticket.opened_at);
  return (
    <li>
      <Link
        to="/my-tickets/$taskId"
        params={{ taskId: String(ticket.task_id) }}
        className="flex items-center gap-3 px-4 py-3 hover:bg-muted focus-visible:bg-muted"
      >
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-sm">
            {ticket.subject || t(`streams.${ticket.stream}.title`)}
          </p>
          <p className="text-muted-foreground text-xs">
            {t(`streams.${ticket.stream}.title`)} · {moved}
          </p>
        </div>
        <TicketStateBadge state={ticket.state} />
      </Link>
    </li>
  );
};

export const MyTicketsPage = () => {
  const { t } = useTranslation(["intake", "nav"]);
  const { data, isLoading, isError } = useFiledTickets();
  const items = data?.items ?? [];

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6">
      <h1 className="font-semibold text-3xl tracking-tight">{t("nav:myTickets")}</h1>
      {isLoading ? (
        <SkeletonRegion>
          <Skeleton className="h-48 w-full" />
        </SkeletonRegion>
      ) : isError ? (
        <p className="py-8 text-center text-destructive text-sm">{t("tickets.loadError")}</p>
      ) : items.length === 0 ? (
        <p className="py-8 text-center text-muted-foreground text-sm">{t("tickets.empty")}</p>
      ) : (
        <Card className="overflow-hidden p-0">
          <ul className="divide-y">
            {items.map((ticket) => (
              <TicketRow key={ticket.task_id} ticket={ticket} />
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
};
