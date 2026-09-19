import { Link, useLocation, useParams } from "@tanstack/react-router";
import type { SerializedEditorState } from "lexical";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool, WikiPageKind, WikiReadingWidth } from "@/api/generated/initiativeAPI.schemas";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { Editor } from "@/components/documents/editor/editor";
import { WikiChrome } from "@/components/initiativeTools/wikis/WikiChrome";
import { WikiPageConnections } from "@/components/initiativeTools/wikis/WikiPageConnections";
import { WikiPageNav } from "@/components/initiativeTools/wikis/WikiPageNav";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useDocument } from "@/hooks/useDocuments";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useWiki } from "@/hooks/useWikis";
import { useGuildPath } from "@/lib/guildUrl";
import { toolDetailRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

/**
 * A document, read as a page of the wiki it was put in.
 *
 * The same chrome and the same column a page of the wiki's own gets, because
 * that is the point of putting it here — it is read with the wiki's navigation
 * beside it rather than as a detour out of one.
 *
 * It is never editable here. A document in a wiki is still that document: it
 * has its own address, its own sharing and its own history, and writing it
 * happens there. So the writing control leaves rather than switching a mode,
 * and nothing on this screen can change what is written.
 */
export const WikiDocumentView = () => {
  const { t } = useTranslation(["wikis", "common"]);
  const gp = useGuildPath();
  const {
    wikiId: wikiIdParam,
    documentId: documentIdParam,
    initiativeId: initiativeIdParam,
  } = useParams({ strict: false }) as {
    wikiId?: string;
    documentId?: string;
    initiativeId?: string;
  };

  const wikiId = Number(wikiIdParam);
  const documentId = Number(documentIdParam);
  const initiativeId = Number(initiativeIdParam);
  const validIds = Number.isFinite(wikiId) && Number.isFinite(documentId);

  const wikiQuery = useWiki(validIds ? wikiId : null);
  const documentQuery = useDocument(validIds ? documentId : null);

  const wiki = wikiQuery.data;
  const document_ = documentQuery.data;

  const [commentsOpen, setCommentsOpen] = useState(false);
  const [showConnections, setShowConnections] = useState(true);
  const [railAsked, setRailAsked] = useState(false);
  const railFitsBeside = useMediaQuery("(min-width: 1280px)");

  // Arriving at a heading, the same way a page of the wiki's own does.
  const hash = useLocation({ select: (location) => location.hash });
  useEffect(() => {
    if (!hash || !document_) return;
    let cancelled = false;
    const find = () => {
      if (cancelled) return;
      const heading = window.document.getElementById(hash);
      if (heading) heading.scrollIntoView({ behavior: "smooth", block: "start" });
      else requestAnimationFrame(find);
    };
    requestAnimationFrame(find);
    return () => {
      cancelled = true;
    };
  }, [hash, document_]);

  const body = useMemo(() => {
    const stored = document_?.content as SerializedEditorState | undefined;
    const children = stored?.root?.children;
    return Array.isArray(children) && children.length > 0 ? stored : null;
  }, [document_?.content]);

  if (!validIds || documentQuery.isError) {
    return (
      <Card className="mx-auto mt-10 max-w-md">
        <CardHeader>
          <CardTitle>{t("pages.notFound")}</CardTitle>
          <CardDescription>{t("notFoundDescription")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (!wiki) {
    return <p className="p-6 text-muted-foreground text-sm">{t("pages.loading")}</p>;
  }

  const isComfortable = wiki.reading_width === WikiReadingWidth.comfortable;
  const railOpen = showConnections && wiki.show_connections && Boolean(document_);

  return (
    <>
      <div className="flex h-full min-h-0 flex-col">
        <WikiChrome
          wiki={wiki}
          pageTitle={document_?.name || t("pages.untitled")}
          pageUpdatedAt={document_?.updated_at}
          // Writing happens where the document lives, so this screen offers no
          // mode to enter.
          canWrite={false}
          editing={false}
          onToggleEditing={() => {}}
          onOpenComments={() => setCommentsOpen(true)}
          commentsEnabled={document_?.comments_enabled ?? false}
          onToggleConnections={() => {
            setRailAsked(true);
            setShowConnections((shown) => !shown);
          }}
          connectionsOpen={showConnections}
          trailing={
            <Button variant="outline" size="sm" className="h-8" asChild>
              <Link to={gp(toolDetailRoute(Tool.document, initiativeId, documentId))}>
                {t("documents.openDocument")}
              </Link>
            </Button>
          }
        />

        <div className="flex min-h-0 flex-1">
          <div className="min-w-0 flex-1 overflow-y-auto">
            <div
              className={cn(
                "mx-auto w-full px-6 py-8 lg:px-10",
                isComfortable ? "max-w-3xl" : "max-w-6xl"
              )}
            >
              {document_ ? (
                <>
                  <Editor
                    key={documentId}
                    editorSerializedState={body ?? undefined}
                    readOnly
                    showToolbar={false}
                    className="rounded-none border-0 bg-transparent shadow-none"
                    initiativeId={Number.isFinite(initiativeId) ? initiativeId : null}
                    subject={`document:${documentId}`}
                    supportsEntityMentions
                    compact
                  />
                  {/* A borrowed document is a page of this wiki while you are
                      reading it here, so it leads on like one. */}
                  <WikiPageNav
                    wikiId={wikiId}
                    initiativeId={initiativeId}
                    currentId={documentId}
                    currentKind={WikiPageKind.document}
                  />
                </>
              ) : (
                <div className="space-y-4">
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-11/12" />
                  <Skeleton className="h-4 w-4/5" />
                </div>
              )}
            </div>
          </div>

          {railOpen && railFitsBeside ? (
            <div className="flex w-72 shrink-0 flex-col overflow-y-auto py-6 pr-6">
              <WikiPageConnections wikiId={wikiId} pageId={documentId} className="min-h-0" />
            </div>
          ) : null}
        </div>
      </div>

      <Sheet
        open={railOpen && !railFitsBeside && railAsked}
        onOpenChange={(open) => !open && setShowConnections(false)}
      >
        <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-sm">
          <SheetHeader className="border-b px-5 py-4">
            <SheetTitle>{t("links.title")}</SheetTitle>
          </SheetHeader>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            <WikiPageConnections
              wikiId={wikiId}
              pageId={documentId}
              className="border-0 shadow-none"
            />
          </div>
        </SheetContent>
      </Sheet>

      <Sheet open={commentsOpen} onOpenChange={setCommentsOpen}>
        <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-lg">
          <SheetHeader className="border-b px-5 py-4">
            <SheetTitle>{t("comments")}</SheetTitle>
          </SheetHeader>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            {/* A document in a wiki is still that document — its thread is
                its own, and is the same one its detail page shows. */}
            {document_ ? <ToolCommentsPanel tool={Tool.document} entity={document_} /> : null}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
};
