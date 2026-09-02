import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ContactRead } from "@/api/generated/initiativeAPI.schemas";
import { ContactRow } from "@/components/contacts/ContactRow";
import type { ChipGuild } from "@/components/contacts/SharedGuildChip";
import { AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";

interface ContactSectionProps {
  value: string;
  /** The heading — a guild's icon and name, or the Favorites label. */
  title: ReactNode;
  count: number;
  items: ContactRead[];
  starredIds: Set<number>;
  onToggleFavorite: (contact: ContactRead) => void;
  omitGuildId?: number;
  guilds: Map<number, ChipGuild>;
  emptyLabel: string;
  /** Present only where more of this section remains to load. */
  onLoadMore?: () => void;
  isLoadingMore?: boolean;
}

/**
 * One collapsible section of the page.
 *
 * Favorites and a community's roster are the same component: both are a
 * heading, a count, and a list of the same row. What differs is only which
 * guild the chip drops and whether there are more pages behind it.
 */
export const ContactSection = ({
  value,
  title,
  count,
  items,
  starredIds,
  onToggleFavorite,
  omitGuildId,
  guilds,
  emptyLabel,
  onLoadMore,
  isLoadingMore,
}: ContactSectionProps) => {
  const { t } = useTranslation("contacts");

  return (
    <AccordionItem value={value}>
      <AccordionTrigger className="gap-2">
        <span className="flex min-w-0 flex-1 items-center gap-2">{title}</span>
        <span className="mr-2 shrink-0 text-muted-foreground text-xs tabular-nums">{count}</span>
      </AccordionTrigger>
      <AccordionContent>
        {items.length === 0 ? (
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
        {onLoadMore ? (
          <div className="px-2 pt-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onLoadMore}
              disabled={isLoadingMore}
            >
              {isLoadingMore ? <Loader2 className="mr-2 size-4 animate-spin" /> : null}
              {t("loadMore")}
            </Button>
          </div>
        ) : null}
      </AccordionContent>
    </AccordionItem>
  );
};
