import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ContactRead } from "@/api/generated/initiativeAPI.schemas";
import { ContactRowsSkeleton } from "@/components/contacts/ContactColumns";
import { ContactRow } from "@/components/contacts/ContactRow";
import type { ChipGuild } from "@/components/contacts/SharedGuildChip";
import { PaginationBar } from "@/components/PaginationBar";
import { AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";

interface ContactSectionProps {
  value: string;
  /** The heading — a guild's icon and name, or the Favorites label. */
  title: ReactNode;
  /** The heading in words, for the pager's own label. */
  label: string;
  items: ContactRead[];
  starredIds: Set<number>;
  onToggleFavorite: (contact: ContactRead) => void;
  omitGuildId?: number;
  guilds: Map<number, ChipGuild>;
  emptyLabel: string;
  /** Everyone this section holds, not just the page on screen. */
  totalCount: number;
  page: number;
  pageSize: number;
  onPageChange: (updater: number | ((prev: number) => number)) => void;
  onPrefetchPage?: (page: number) => void;
  /** The page on screen is on its way; rows stand in until it lands. */
  isLoadingPage?: boolean;
  /** The page on screen did not arrive. Said plainly — an empty section here
   *  would claim the community is empty, which is the opposite of true. */
  hasPageError?: boolean;
  onRetryPage?: () => void;
}

/**
 * One collapsible section of the page.
 *
 * Favorites and a community's roster are the same component: both are a
 * heading, a count, and a list of the same row on the same columns. What
 * differs is only which guild the chip drops and where the pages come from.
 *
 * The pager is part of the section rather than something that appears once
 * there is a second page, so paging never moves the section under the cursor.
 */
export const ContactSection = ({
  value,
  title,
  label,
  items,
  starredIds,
  onToggleFavorite,
  omitGuildId,
  guilds,
  emptyLabel,
  totalCount,
  page,
  pageSize,
  onPageChange,
  onPrefetchPage,
  isLoadingPage,
  hasPageError,
  onRetryPage,
}: ContactSectionProps) => {
  const { t } = useTranslation("contacts");
  const remaining = Math.max(0, Math.min(pageSize, totalCount - (page - 1) * pageSize));

  return (
    <AccordionItem value={value} className="border-b last:border-b-0">
      <AccordionTrigger className="gap-2 px-2 py-2.5 hover:no-underline">
        <span className="flex min-w-0 flex-1 items-center gap-2">{title}</span>
        <span className="mr-2 shrink-0 text-muted-foreground text-xs tabular-nums">
          <span aria-hidden="true">{totalCount}</span>
          <span className="sr-only">{t("peopleCount", { count: totalCount })}</span>
        </span>
      </AccordionTrigger>
      <AccordionContent className="pb-3">
        {isLoadingPage ? (
          <ContactRowsSkeleton count={Math.max(1, remaining)} />
        ) : hasPageError ? (
          <div className="flex flex-wrap items-center gap-3 px-2 pb-2">
            <p className="text-muted-foreground text-sm">{t("pageError.description")}</p>
            {onRetryPage ? (
              <Button type="button" variant="outline" size="sm" onClick={onRetryPage}>
                {t("pageError.retry")}
              </Button>
            ) : null}
          </div>
        ) : items.length === 0 ? (
          <p className="px-2 pb-2 text-muted-foreground text-sm">{emptyLabel}</p>
        ) : (
          <ul className="space-y-0.5">
            {items.map((contact) => (
              <ContactRow
                key={contact.id}
                contact={contact}
                starred={starredIds.has(contact.id)}
                onToggleFavorite={onToggleFavorite}
                omitGuildId={omitGuildId}
                guilds={guilds}
              />
            ))}
          </ul>
        )}
        {totalCount > 0 ? (
          <PaginationBar
            className="px-2 pt-3"
            label={t("pagerLabel", { section: label })}
            page={page}
            pageSize={pageSize}
            totalCount={totalCount}
            hasNext={page * pageSize < totalCount}
            onPageChange={onPageChange}
            onPrefetchPage={onPrefetchPage}
          />
        ) : null}
      </AccordionContent>
    </AccordionItem>
  );
};
