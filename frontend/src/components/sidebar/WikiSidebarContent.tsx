import { Link, useNavigate } from "@tanstack/react-router";
import { ChevronLeft, FilePlus, Search, Settings } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool, WikiPageKind, type WikiPageSummary } from "@/api/generated/initiativeAPI.schemas";
import { AddWikiDocumentDialog } from "@/components/initiativeTools/wikis/AddWikiDocumentDialog";
import { WikiPageActions } from "@/components/initiativeTools/wikis/WikiPageActions";
import { WikiPageTree } from "@/components/initiativeTools/wikis/WikiPageTree";
import { Button } from "@/components/ui/button";
import {
  SidebarContent,
  SidebarGroup,
  SidebarHeader,
  SidebarInput,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import {
  useCreateWikiPage,
  useMoveWikiDocument,
  useMoveWikiPage,
  useRemoveWikiDocument,
  useWiki,
  useWikiPages,
} from "@/hooks/useWikis";
import { toast } from "@/lib/chesterToast";
import { useGuildPath } from "@/lib/guildUrl";
import { TOOL_ICONS, toolSettingsRoute, wikiDocumentRoute, wikiPageRoute } from "@/lib/tools";

// Adding a document to a wiki is named by the documents tool itself, so the row
// says which tool it reaches into rather than inventing a second mark for it.
const DocumentIcon = TOOL_ICONS[Tool.document];

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
  // Putting a document in the wiki, and taking one back out.
  const [addingDocument, setAddingDocument] = useState(false);
  const removeDocument = useRemoveWikiDocument(wikiId);
  const movePage = useMoveWikiPage(wikiId);
  const moveDocument = useMoveWikiDocument(wikiId);

  const pages = pagesQuery.data?.items ?? [];

  // Searching a wiki is finding a page in it, so this filters the tree rather
  // than opening the palette: the answer is a list of pages, and the list is
  // already on screen.
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();
  const matches = useMemo(
    () => (needle ? pages.filter((page) => page.title.toLowerCase().includes(needle)) : []),
    [pages, needle]
  );
  // Writing is the wiki's own gate, so the add affordances appear exactly
  // where the server would accept one.
  const canWrite =
    wikiQuery.data?.my_permission_level === "write" ||
    wikiQuery.data?.my_permission_level === "owner";

  const addPage = () =>
    createPage.mutate(
      {},
      {
        onSuccess: (page) =>
          void navigate({ to: gp(wikiPageRoute(initiativeId, wikiId, page.id)) }),
      }
    );

  // A drop tells the server where the page landed; the tree is then redrawn
  // from what comes back rather than from what the drag guessed.
  const movePageTo = (page: WikiPageSummary, parentPageId: number | null, position: number) => {
    // Both kinds of row sit in one tree; which endpoint keeps their place is
    // the only thing that differs, because a document's place belongs to the
    // wiki — and it is always at the top of it, so it is never filed under a
    // page.
    if (page.kind === WikiPageKind.document) {
      moveDocument.mutate({ documentId: page.id, position });
    } else {
      movePage.mutate({ pageId: page.id, parent_page_id: parentPageId, position });
    }
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
            <Button variant="ghost" size="icon" className="size-8 shrink-0" asChild>
              <Link to={gp(toolSettingsRoute(Tool.wiki, initiativeId, wikiId))}>
                <Settings className="size-4" aria-hidden />
                <span className="sr-only">{t("settings.title")}</span>
              </Link>
            </Button>
          ) : null}
        </div>
      </SidebarHeader>

      <div className="relative border-b">
        <Search
          className="pointer-events-none absolute top-2.5 left-4 size-4 text-muted-foreground"
          aria-hidden
        />
        <SidebarInput
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("pages.searchPlaceholder")}
          aria-label={t("pages.search")}
          className="h-9 border-0 bg-transparent pl-9 shadow-none focus-visible:ring-0"
        />
      </div>

      <SidebarContent className="h-full overflow-y-auto overflow-x-hidden">
        <SidebarGroup>
          {pagesQuery.isLoading ? (
            <p className="px-2 py-1.5 text-muted-foreground text-sm">{t("pages.loading")}</p>
          ) : needle ? (
            matches.length === 0 ? (
              <p className="px-2 py-1.5 text-muted-foreground text-sm">
                {t("pages.searchEmpty", { query: query.trim() })}
              </p>
            ) : (
              <SidebarMenu>
                {matches.map((page) => (
                  <SidebarMenuItem key={page.id}>
                    <SidebarMenuButton asChild size="sm" isActive={page.id === activePageId}>
                      <Link
                        to={gp(
                          page.kind === WikiPageKind.document
                            ? wikiDocumentRoute(initiativeId, wikiId, page.id)
                            : wikiPageRoute(initiativeId, wikiId, page.id)
                        )}
                      >
                        <span className="min-w-0 flex-1 truncate">
                          {page.title || t("pages.untitled")}
                        </span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            )
          ) : (
            <>
              <WikiPageTree
                pages={pages}
                activePageId={activePageId}
                homePageId={wikiQuery.data?.home_page_id}
                hrefOf={(page) =>
                  gp(
                    page.kind === WikiPageKind.document
                      ? wikiDocumentRoute(initiativeId, wikiId, page.id)
                      : wikiPageRoute(initiativeId, wikiId, page.id)
                  )
                }
                onMove={canWrite ? movePageTo : undefined}
                renderRowMenu={
                  canWrite && wikiQuery.data
                    ? (page) => (
                        <WikiPageActions
                          wiki={wikiQuery.data}
                          page={page}
                          canWrite={canWrite}
                          initiativeId={initiativeId}
                          onRemoveDocument={() =>
                            removeDocument.mutate(page.id, {
                              onSuccess: () => toast.success(t("documents.removed")),
                            })
                          }
                        />
                      )
                    : undefined
                }
                accentColor={wikiQuery.data?.accent_color}
              />
              {canWrite ? (
                <SidebarMenu>
                  <SidebarMenuItem>
                    <SidebarMenuButton
                      size="sm"
                      onClick={() => addPage()}
                      disabled={createPage.isPending}
                    >
                      <FilePlus className="h-4 w-4" />
                      <span>{t("pages.newPage")}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                  <SidebarMenuItem>
                    <SidebarMenuButton size="sm" onClick={() => setAddingDocument(true)}>
                      <DocumentIcon className="h-4 w-4" />
                      <span>{t("documents.addDocument")}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                </SidebarMenu>
              ) : null}
            </>
          )}
        </SidebarGroup>
      </SidebarContent>

      <AddWikiDocumentDialog
        wikiId={wikiId}
        initiativeId={initiativeId}
        pages={pages}
        open={addingDocument}
        onOpenChange={setAddingDocument}
      />
    </>
  );
};
