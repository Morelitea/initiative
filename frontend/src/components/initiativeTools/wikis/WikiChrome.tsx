import { BookText, Eye, MessageSquare, PanelRight, Pencil, Send } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { WikiRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { RelativeTime } from "@/components/ui/relative-time";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

interface WikiChromeProps {
  wiki: WikiRead;
  /** The page being read. This bar names where you are, not where you are in general. */
  pageTitle: string;
  /** Renames the page. Present only while it is open for editing. */
  onRename?: (title: string) => void;
  /** Sends the name now, rather than waiting out the pause — on blur, or Enter. */
  onRenameCommit?: () => void;
  /** When that page was last written to, shown when the wiki asks for it. */
  pageUpdatedAt?: string | null;
  /** Whether the reader may write, which is what makes editing offerable. */
  canWrite: boolean;
  /** Whether the page is open for editing rather than being read. */
  editing: boolean;
  /** Whether this page is still a draft — written, but not yet part of the
   *  wiki for the people who only read it. */
  isDraft?: boolean;
  /** Publishes the draft. Absent when there is nothing to publish. */
  onPublish?: () => void;
  onToggleEditing: () => void;
  onOpenComments: () => void;
  /** Whether there is a thread to open. The wiki answers for its own pages;
   *  a borrowed document answers for itself. */
  commentsEnabled?: boolean;
  onToggleConnections: () => void;
  connectionsOpen: boolean;
  /** Anything this particular surface adds — a way out to a document, say. */
  trailing?: ReactNode;
}

/**
 * The bar a wiki wears across the top of every one of its pages.
 *
 * It names the page being read, because that is what somebody needs from the
 * top of the screen — the wiki's own name already stands at the head of the
 * column its pages are in.
 *
 * What acts on the whole wiki and belongs over every page of it — the
 * conversation, the reading mode, whether the rail is showing — lives here.
 * Making a page and configuring the wiki do not: a page is a place in the
 * tree, so it is made in the tree, and the settings are a screen of their own.
 *
 * The accent is the wiki's own, so two open in two tabs are told apart before
 * either name is read.
 */
export const WikiChrome = ({
  wiki,
  pageTitle,
  onRename,
  onRenameCommit,
  pageUpdatedAt,
  canWrite,
  editing,
  isDraft = false,
  onPublish,
  onToggleEditing,
  onOpenComments,
  commentsEnabled,
  onToggleConnections,
  connectionsOpen,
  trailing,
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
        {/* The page's name lives here and nowhere else. A wiki page is a page
            on a site, and a site does not print its own address twice. */}
        {onRename ? (
          <Input
            value={pageTitle}
            onChange={(event) => onRename(event.target.value)}
            onBlur={onRenameCommit}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                onRenameCommit?.();
              }
            }}
            aria-label={t("pages.titleLabel")}
            placeholder={t("pages.titlePlaceholder")}
            className="h-auto border-0 px-0 py-0 font-semibold text-base leading-tight shadow-none focus-visible:ring-0"
          />
        ) : (
          <h1 className="flex min-w-0 items-center gap-2 font-semibold text-base leading-tight">
            <span className="truncate">{pageTitle}</span>
            {/* Said where the page is named, because "who can see this" is the
                first thing to know about a page you are looking at. */}
            {isDraft ? (
              <span className="shrink-0 rounded border px-1 text-[10px] text-muted-foreground uppercase">
                {t("pages.draft")}
              </span>
            ) : null}
          </h1>
        )}
        {/* A handbook people act on needs to say how old it is; the wiki
            decides whether that is true of it. */}
        {wiki.show_updated_at && pageUpdatedAt ? (
          <p className="truncate text-muted-foreground text-xs">
            {t("updated")} <RelativeTime date={pageUpdatedAt} />
          </p>
        ) : null}
      </div>

      <div className="flex shrink-0 items-center gap-1">
        {trailing}

        {/* A page is written before it is published, so the one thing a writer
            is most likely to want next has a button of its own rather than a
            place in a menu. It goes when the page is published, because then
            there is nothing left to do. */}
        {canWrite && isDraft && onPublish ? (
          <Button variant="default" size="sm" className="h-8 gap-1.5" onClick={onPublish}>
            <Send className="size-4" aria-hidden />
            {t("page.publish")}
          </Button>
        ) : null}

        {/* Reading is the default, and editing is a mode somebody enters. A
            wiki is read far more often than it is written, and what a reader
            sees is the thing a writer most needs to check. */}
        {canWrite ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={editing ? "secondary" : "ghost"}
                size="icon"
                className="size-8"
                onClick={onToggleEditing}
                aria-pressed={editing}
                aria-label={editing ? t("viewMode.read") : t("viewMode.edit")}
              >
                {editing ? (
                  <Eye className="size-4" aria-hidden />
                ) : (
                  <Pencil className="size-4" aria-hidden />
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{editing ? t("viewMode.read") : t("viewMode.edit")}</TooltipContent>
          </Tooltip>
        ) : null}

        {(commentsEnabled ?? wiki.comments_enabled) ? (
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

        {wiki.show_connections ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className={cn("size-8", connectionsOpen && "bg-accent")}
                onClick={onToggleConnections}
                aria-pressed={connectionsOpen}
                aria-label={t("links.title")}
              >
                <PanelRight className="size-4" aria-hidden />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("links.title")}</TooltipContent>
          </Tooltip>
        ) : null}
      </div>
    </header>
  );
};
