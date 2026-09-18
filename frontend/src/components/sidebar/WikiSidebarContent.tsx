import { useNavigate } from "@tanstack/react-router";
import { ChevronLeft, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { WikiPageSummary } from "@/api/generated/initiativeAPI.schemas";
import { WikiPageTree } from "@/components/initiativeTools/wikis/WikiPageTree";
import { Button } from "@/components/ui/button";
import { SidebarContent, SidebarGroup, SidebarHeader } from "@/components/ui/sidebar";
import { useCreateWikiPage, useMoveWikiPage, useWiki, useWikiPages } from "@/hooks/useWikis";
import { useGuildPath } from "@/lib/guildUrl";
import { wikiPageRoute } from "@/lib/tools";

interface WikiSidebarContentProps {
  wikiId: number;
  initiativeId: number;
  /** The page the reader is on, so the tree marks it. */
  activePageId?: number | null;
  /** Climbs back out to the ordinary navigation. */
  onBack: () => void;
}

/**
 * A wiki's pages, in the column the navigation was in.
 *
 * A wiki is a list of pages and then one of them, which is two levels in a
 * place that has room for one. So opening a wiki drills, exactly as My
 * Messages does: the page tree takes the sidebar and the arrow in the header
 * climbs back out.
 *
 * The tree is the navigation here — not a panel beside the text — because that
 * is what separates a wiki from a folder of documents: you read it by moving
 * around it, and the shape has to be in front of you the whole time.
 */
export const WikiSidebarContent = ({
  wikiId,
  initiativeId,
  activePageId,
  onBack,
}: WikiSidebarContentProps) => {
  const { t } = useTranslation("wikis");
  const gp = useGuildPath();
  const navigate = useNavigate();

  const wikiQuery = useWiki(wikiId);
  const pagesQuery = useWikiPages(wikiId);
  const createPage = useCreateWikiPage(wikiId);
  // The page a drag is moving. The mutation is per page, so the hook is built
  // for whichever one the tree hands over — `0` while none is in flight, which
  // the tree never triggers.
  const [movingPageId, setMovingPageId] = useState(0);
  const movePage = useMoveWikiPage(wikiId, movingPageId);

  const pages = pagesQuery.data?.items ?? [];
  // Writing is the wiki's own gate, so the add affordances appear exactly
  // where the server would accept one.
  const canWrite =
    wikiQuery.data?.my_permission_level === "write" ||
    wikiQuery.data?.my_permission_level === "owner";

  const addPage = (parent?: WikiPageSummary) =>
    createPage.mutate(
      { title: t("pages.untitled"), parent_page_id: parent?.id ?? null },
      {
        onSuccess: (page) =>
          void navigate({ to: gp(wikiPageRoute(initiativeId, wikiId, page.id)) }),
      }
    );

  // A drop tells the server where the page landed; the tree is then redrawn
  // from what comes back rather than from what the drag guessed.
  const movePageTo = (page: WikiPageSummary, parentPageId: number | null, position: number) => {
    setMovingPageId(page.id);
    movePage.mutate({ parent_page_id: parentPageId, position });
  };

  return (
    <>
      <SidebarHeader
        className="gap-0 border-b p-0"
        style={{ paddingTop: "var(--safe-area-inset-top)" }}
      >
        <div className="flex h-12 min-w-0 items-center gap-1 px-1.5">
          <Button variant="ghost" size="icon" className="size-8 shrink-0" onClick={onBack}>
            <ChevronLeft className="size-4" aria-hidden />
            <span className="sr-only">{t("backToWikis")}</span>
          </Button>
          <h2 className="min-w-0 flex-1 truncate font-semibold text-lg">
            {wikiQuery.data?.name ?? t("title")}
          </h2>
          {canWrite ? (
            <Button
              variant="ghost"
              size="icon"
              className="size-8 shrink-0"
              onClick={() => addPage()}
              disabled={createPage.isPending}
            >
              <Plus className="size-4" aria-hidden />
              <span className="sr-only">{t("pages.newPage")}</span>
            </Button>
          ) : null}
        </div>
      </SidebarHeader>

      <SidebarContent className="h-full overflow-y-auto overflow-x-hidden">
        <SidebarGroup>
          {pagesQuery.isLoading ? (
            <p className="px-2 py-1.5 text-muted-foreground text-sm">{t("pages.loading")}</p>
          ) : (
            <WikiPageTree
              pages={pages}
              activePageId={activePageId}
              homePageId={wikiQuery.data?.home_page_id}
              hrefOf={(page) => gp(wikiPageRoute(initiativeId, wikiId, page.id))}
              onAddChild={canWrite ? addPage : undefined}
              onMove={canWrite ? movePageTo : undefined}
            />
          )}
        </SidebarGroup>
      </SidebarContent>
    </>
  );
};
