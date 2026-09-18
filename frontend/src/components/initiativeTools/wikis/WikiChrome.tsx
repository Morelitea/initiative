import { BookText, MessageSquare, PanelRight, Plus, Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { WikiRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

interface WikiChromeProps {
  wiki: WikiRead;
  canWrite: boolean;
  onAddPage: () => void;
  onOpenComments: () => void;
  onOpenSettings: () => void;
  onToggleConnections: () => void;
  connectionsOpen: boolean;
}

/**
 * The bar a wiki wears across the top of every one of its pages.
 *
 * This is what makes the surface read as a place rather than a document: the
 * wiki's name and what it covers stay put while you move between pages, and
 * the things that act on the whole wiki — adding a page, the conversation, the
 * settings — live here rather than repeating down each page.
 *
 * The accent is the wiki's own, so two open in two tabs are told apart before
 * either name is read.
 */
export const WikiChrome = ({
  wiki,
  canWrite,
  onAddPage,
  onOpenComments,
  onOpenSettings,
  onToggleConnections,
  connectionsOpen,
}: WikiChromeProps) => {
  const { t } = useTranslation("wikis");
  const accent = wiki.accent_color ?? undefined;

  return (
    <header
      className="flex shrink-0 items-center gap-3 border-b bg-card/40 px-4 py-2.5 lg:px-6"
      // A hairline of the wiki's colour down the leading edge. Enough to
      // identify it; not enough to compete with what is written.
      style={accent ? { boxShadow: `inset 3px 0 0 0 ${accent}` } : undefined}
    >
      <span
        className="flex size-8 shrink-0 items-center justify-center rounded-md border bg-background"
        style={accent ? { color: accent, borderColor: accent } : undefined}
      >
        <BookText className="size-4" aria-hidden />
      </span>

      <div className="min-w-0 flex-1">
        <h1 className="truncate font-semibold text-base leading-tight">{wiki.name}</h1>
        {wiki.description ? (
          <p className="truncate text-muted-foreground text-xs">{wiki.description}</p>
        ) : null}
      </div>

      <div className="flex shrink-0 items-center gap-1">
        {canWrite ? (
          <Button variant="outline" size="sm" className="h-8" onClick={onAddPage}>
            <Plus className="size-4" aria-hidden />
            <span className="hidden sm:inline">{t("newPage")}</span>
          </Button>
        ) : null}

        {wiki.comments_enabled ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="size-8"
                onClick={onOpenComments}
                aria-label={t("comments")}
              >
                <MessageSquare className="size-4" aria-hidden />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("comments")}</TooltipContent>
          </Tooltip>
        ) : null}

        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className={cn("hidden size-8 lg:inline-flex", connectionsOpen && "bg-accent")}
              onClick={onToggleConnections}
              aria-pressed={connectionsOpen}
              aria-label={t("links.title")}
            >
              <PanelRight className="size-4" aria-hidden />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{t("links.title")}</TooltipContent>
        </Tooltip>

        {canWrite ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="size-8"
                onClick={onOpenSettings}
                aria-label={t("settings.title")}
              >
                <Settings2 className="size-4" aria-hidden />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("settings.title")}</TooltipContent>
          </Tooltip>
        ) : null}
      </div>
    </header>
  );
};
