/**
 * "Ask for help", in the sidebar's bottom row.
 *
 * Here wherever there is somebody to ask: a community that takes help
 * requests gets the form, and where the deployment takes none but has said who
 * to write to, the button shows that address. Where there is neither, it is
 * not drawn — the documentation has a button of its own beside it, so a dead
 * end never stands in for one.
 */

import { LifeBuoy } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ContactDialog } from "@/components/tickets/ContactDialog";
import { FileTicketDialog } from "@/components/tickets/FileTicketDialog";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useTicketAvailability } from "@/hooks/useTickets";

export const AskForHelpButton = () => {
  const { t } = useTranslation("intake");
  const guildId = useActiveGuildId();
  const [open, setOpen] = useState(false);
  const { data } = useTicketAvailability(guildId);

  // The sidebar stays mounted across a community switch, so a request opened
  // in one could be sent to the next. Changing community closes it: a help
  // request is about where you were, and carrying the words across would send
  // them to people the writer never meant.
  useEffect(() => {
    setOpen(false);
  }, [guildId]);

  const support = data?.support;
  const canAsk = support?.mode === "form" && guildId != null;
  const contact = support?.mode === "email" ? support.contact : null;
  // Nobody to ask from here, or no answer yet: nothing is drawn rather than a
  // control that would lead nowhere.
  if (!canAsk && !contact) return null;

  const label = t("help.action");

  return (
    <>
      {/* Its own provider. The sidebar supplies one where this is drawn, but
          carrying one means the control cannot be moved somewhere without. */}
      <TooltipProvider delayDuration={300}>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              className="cursor-pointer text-muted-foreground transition-colors hover:text-foreground"
              aria-label={label}
              onClick={() => setOpen(true)}
            >
              <LifeBuoy className="h-4 w-4" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="top">
            <p>{label}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
      {open && canAsk ? (
        // Keyed on the community as well, so nothing typed can outlive the one
        // it was typed in even if the close above were ever missed.
        <FileTicketDialog
          key={guildId}
          open={open}
          onOpenChange={setOpen}
          ticket={{ stream: "support" }}
          guildId={guildId}
        />
      ) : open && contact ? (
        <ContactDialog open={open} onOpenChange={setOpen} contact={contact} />
      ) : null}
    </>
  );
};
