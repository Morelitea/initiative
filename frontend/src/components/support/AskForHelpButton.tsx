/**
 * "Ask for help", in the sidebar's bottom row.
 *
 * Always here, whatever the community has decided — somebody who needs help
 * should not have to find out first whether there is anybody to ask. What it
 * does is what changes: a community that takes help requests gets the form,
 * and everywhere else — including outside any community — it opens the FAQ,
 * which is the answer to most of what would be typed into the form anyway.
 */

import { CircleQuestionMark } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { AskForHelpDialog } from "@/components/support/AskForHelpDialog";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { FAQ_URL, useSupportAvailability } from "@/hooks/useSupport";

const ICON_CLASS = "text-muted-foreground transition-colors hover:text-foreground";

export const AskForHelpButton = () => {
  const { t } = useTranslation("intake");
  const guildId = useActiveGuildId();
  const [open, setOpen] = useState(false);
  // A failed or unfinished read leaves the FAQ, which is the honest fallback:
  // the form is the thing that needs an answer to work.
  const { data } = useSupportAvailability(guildId);

  // The sidebar stays mounted across a community switch, so a request opened
  // in one could be sent to the next. Changing community closes it: a help
  // request is about where you were, and carrying the words across would send
  // them to people the writer never meant.
  useEffect(() => {
    setOpen(false);
  }, [guildId]);

  const label = t("help.action");
  const canAsk = Boolean(data?.available) && guildId != null;

  return (
    <>
      {/* Its own provider. The sidebar supplies one where this is drawn, but
          carrying one means the control cannot be moved somewhere without. */}
      <TooltipProvider delayDuration={300}>
        <Tooltip>
          <TooltipTrigger asChild>
            {canAsk ? (
              <button
                type="button"
                className={`${ICON_CLASS} cursor-pointer`}
                aria-label={label}
                onClick={() => setOpen(true)}
              >
                <CircleQuestionMark className="h-4 w-4" />
              </button>
            ) : (
              <a
                href={FAQ_URL}
                target="_blank"
                rel="noopener noreferrer"
                className={ICON_CLASS}
                aria-label={label}
              >
                <CircleQuestionMark className="h-4 w-4" />
              </a>
            )}
          </TooltipTrigger>
          <TooltipContent side="top">
            <p>{label}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
      {open && guildId != null ? (
        // Keyed on the community as well, so nothing typed can outlive the one
        // it was typed in even if the close above were ever missed.
        <AskForHelpDialog key={guildId} open={open} onOpenChange={setOpen} guildId={guildId} />
      ) : null}
    </>
  );
};
