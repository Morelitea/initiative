import { useLocation, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import type { SerializedEditorState } from "lexical";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool, WikiReadingWidth } from "@/api/generated/initiativeAPI.schemas";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { Editor } from "@/components/documents/editor/editor";
import { WikiChrome } from "@/components/initiativeTools/wikis/WikiChrome";
import { WikiPageConnections } from "@/components/initiativeTools/wikis/WikiPageConnections";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useCollaboration } from "@/hooks/useCollaboration";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useCreateWikiPage, useUpdateWikiPage, useWiki, useWikiPage } from "@/hooks/useWikis";
import { toast } from "@/lib/chesterToast";
import { useGuildPath } from "@/lib/guildUrl";
import { wikiPageRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

/**
 * One page of a wiki: its title, its body, and what connects to it.
 *
 * The page tree is NOT here — it has taken the sidebar (see
 * `WikiSidebarContent`), which is the whole navigation model of this tool. What
 * is here is the reading column and, beneath it, the connections: what this
 * page names, and what names it.
 *
 * The body is the same Lexical editor a native document uses, so `[[ ]]` links
 * and smart chips work exactly as they do everywhere else — and the backlinks
 * below are the edges the server reads back out of them on save.
 */
export const WikiPageView = () => {
  const { t } = useTranslation(["wikis", "common"]);
  const gp = useGuildPath();
  const {
    wikiId: wikiIdParam,
    pageId: pageIdParam,
    initiativeId: initiativeIdParam,
  } = useParams({ strict: false }) as {
    wikiId?: string;
    pageId?: string;
    initiativeId?: string;
  };

  // Reading or writing. Kept in the address, because the bar over the page and
  // the page's row in the tree both offer it from different React trees, and
  // because a page being edited is then a thing you can link to or reload into.
  // Reading is where everyone starts, writers included.
  const { edit } = useSearch({ strict: false }) as { edit?: true };
  const editWanted = edit === true;

  const wikiId = Number(wikiIdParam);
  const pageId = Number(pageIdParam);
  const initiativeId = Number(initiativeIdParam);
  const validIds = Number.isFinite(wikiId) && Number.isFinite(pageId);

  // Live co-editing, over the same room documents use — a page is just
  // another body the server keeps a Yjs document for. The path names the page
  // through its wiki, the way every other address for it does.
  const collaboration = useCollaboration({
    socketPath: validIds ? `wikis/${wikiId}/pages/${pageId}/collaborate` : null,
    // Only while somebody is writing. A wiki is read far more than it is
    // written, so a reader opens no room and costs the server nothing.
    enabled: validIds && editWanted,
    onError: (error) => {
      toast.error(t("error"), { description: error.message });
    },
  });

  const wikiQuery = useWiki(validIds ? wikiId : null);
  const pageQuery = useWikiPage(validIds ? wikiId : null, validIds ? pageId : null);
  // `mutate` is referentially stable, so effects can depend on it without
  // re-running every render the way the mutation object would make them.
  const { mutate: savePage } = useUpdateWikiPage(wikiId, pageId);

  const canWrite =
    wikiQuery.data?.my_permission_level === "write" ||
    wikiQuery.data?.my_permission_level === "owner";

  // The title is edited in place, and saved on a pause rather than on every
  // keystroke — renaming a page rewrites its slug, which is an address.
  const [title, setTitle] = useState("");
  useEffect(() => setTitle(pageQuery.data?.title ?? ""), [pageQuery.data?.title]);
  const debouncedTitle = useDebouncedValue(title, 600);

  useEffect(() => {
    const current = pageQuery.data?.title;
    const next = debouncedTitle.trim();
    if (!canWrite || !current || !next || next === current) return;
    savePage({ title: next });
  }, [debouncedTitle, canWrite, pageQuery.data?.title, savePage]);

  // The editor reports every keystroke; the server hears about them 2s after
  // somebody stops, the same window a document autosaves on. Saving per change
  // would be a request per character — and each one re-reads the body for the
  // links it names.
  // The newest body, and a counter that says one arrived. The body itself is a
  // ref so a keystroke does not re-render the editor around the person typing.
  const pendingBody = useRef<SerializedEditorState | null>(null);
  const [bodyRevision, setBodyRevision] = useState(0);

  const onBodyChange = useCallback(
    (state: SerializedEditorState) => {
      if (!canWrite) return;
      pendingBody.current = state;
      setBodyRevision((revision) => revision + 1);
    },
    [canWrite]
  );

  // While a room is live it owns the page's content column — it writes the
  // JSON and the Yjs state from one snapshot, so the two always describe the
  // same moment. This tab reports its rendering to the room and stops writing
  // over REST; with no room, this is the only writer.
  const isCollaborating = collaboration.isCollaborating;
  const sendContent = collaboration.sendContent;
  useEffect(() => {
    if (bodyRevision === 0 || pendingBody.current === null) return;
    const timer = setTimeout(() => {
      const body = pendingBody.current;
      if (body === null) return;
      pendingBody.current = null;
      if (isCollaborating) {
        sendContent(body);
        return;
      }
      savePage({ content: body as unknown as Record<string, unknown> });
    }, 2000);
    return () => clearTimeout(timer);
  }, [bodyRevision, savePage, isCollaborating, sendContent]);

  const initialBody = useMemo(
    () => (pageQuery.data?.content ?? null) as SerializedEditorState | null,
    [pageQuery.data?.content]
  );

  const wiki = wikiQuery.data;
  const page = pageQuery.data;

  // Arriving at a heading. The editor stamps each heading's anchor on the
  // element as it renders, so this waits for the body to be on screen rather
  // than firing on navigation — a page opened from a heading in the sidebar is
  // usually being fetched at the moment the link is followed.
  const hash = useLocation({ select: (location) => location.hash });
  useEffect(() => {
    if (!hash || !page) return;
    let cancelled = false;
    const find = () => {
      if (cancelled) return;
      const heading = document.getElementById(hash);
      if (heading) heading.scrollIntoView({ behavior: "smooth", block: "start" });
      else requestAnimationFrame(find);
    };
    requestAnimationFrame(find);
    return () => {
      cancelled = true;
    };
  }, [hash, page]);

  // The conversation is a drawer: a wiki is browsed, and talking about a page
  // is a different activity from reading it.
  const [commentsOpen, setCommentsOpen] = useState(false);
  // Reading or writing. Kept in the address, because the bar over the page and
  // the page's row in the tree both offer it from different React trees, and
  // because a page being edited is then a thing you can link to or reload into.
  // Reading is where everyone starts, writers included.

  // Whether there is gutter to put the rail in. Keyed to the same 1280px the
  // `xl:` classes use, so the measurement and the layout cannot disagree.
  const railFitsBeside = useMediaQuery("(min-width: 1280px)");
  // Whether the connections rail is showing. A per-visit choice: it is
  // reading furniture, not a setting.
  const [showConnections, setShowConnections] = useState(true);
  // Whether the rail was asked for out loud. Beside the words it is furniture
  // and can simply be there; over them it is an interruption, so a narrow
  // screen waits to be asked rather than opening a drawer on arrival.
  const [railAsked, setRailAsked] = useState(false);

  const createPage = useCreateWikiPage(wikiId);
  const navigate = useNavigate();

  const addPage = () =>
    createPage.mutate(
      { title: t("pages.untitled") },
      {
        onSuccess: (created) =>
          void navigate({ to: gp(wikiPageRoute(initiativeId, wikiId, created.id)) }),
      }
    );

  // The screen's primary create action is a page, not another wiki — this is
  // the inside of one.
  useRegisterPrimaryCreateAction(canWrite ? { run: addPage, label: t("newPage") } : null);

  if (!validIds || pageQuery.isError) {
    return (
      <Card className="mx-auto mt-10 max-w-md">
        <CardHeader>
          <CardTitle>{t("pages.notFound")}</CardTitle>
          <CardDescription>{t("notFoundDescription")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  // The wiki is what the chrome is made of, and it is cached across every page
  // in it — so only the first arrival waits. After that the chrome stays put
  // and the column beneath it is what changes, which is what stops a click on
  // a page from blanking the screen and the sidebar with it.
  if (!wiki) {
    return <p className="p-6 text-muted-foreground text-sm">{t("pages.loading")}</p>;
  }

  const isComfortable = wiki.reading_width === WikiReadingWidth.comfortable;
  // Editing needs both the right and the intent — somebody who may write is
  // still reading until they say otherwise.
  const isEditing = canWrite && edit === true;
  // Asked for, allowed by the wiki, and there is a page to have connections.
  const railOpen = showConnections && wiki.show_connections && Boolean(page);

  return (
    <>
      <div className="flex h-full min-h-0 flex-col">
        <WikiChrome
          wiki={wiki}
          pageTitle={isEditing ? title : page?.title || t("pages.untitled")}
          onRename={isEditing ? setTitle : undefined}
          pageUpdatedAt={page?.updated_at}
          canWrite={canWrite}
          editing={isEditing}
          onToggleEditing={() =>
            void navigate({
              to: gp(wikiPageRoute(initiativeId, wikiId, pageId)),
              search: isEditing ? {} : { edit: true },
              replace: true,
            })
          }
          onOpenComments={() => setCommentsOpen(true)}
          onToggleConnections={() => {
            setRailAsked(true);
            setShowConnections((shown) => !shown);
          }}
          connectionsOpen={showConnections}
        />

        <div className="flex min-h-0 flex-1">
          <div className="min-w-0 flex-1 overflow-y-auto">
            {/* The measure. The surface is the window; the words are not, so
                the column is centred in whatever space is left and capped at a
                line length somebody can actually read. Capping it is also what
                keeps the rail from moving the text: on a wide screen the rail
                takes gutter, and the column does not shift at all. */}
            <div
              className={cn(
                "mx-auto w-full px-6 py-8 lg:px-10",
                isComfortable ? "max-w-3xl" : "max-w-6xl"
              )}
            >
              {page ? (
                <>
                  <Editor
                    // Rebuilt rather than switched: the editor captures
                    // whether it is collaborative at first mount and never
                    // re-reads it, so flipping that on a live instance is
                    // outside its contract. Changing the key hands it a fresh
                    // one for the mode being entered.
                    key={`${pageId}:${isEditing ? "edit" : "read"}`}
                    editorSerializedState={initialBody ?? undefined}
                    onSerializedChange={onBodyChange}
                    readOnly={!isEditing}
                    showToolbar={isEditing}
                    // Reading a wiki is reading a web page, so the sheet a
                    // document draws itself comes off. Wiki-local: the class
                    // overrides the variant here and changes nothing about how
                    // a document renders.
                    className={cn(!isEditing && "rounded-none border-0 bg-transparent shadow-none")}
                    collaborative={collaboration.isReady}
                    providerFactory={collaboration.providerFactory}
                    // Always on, so the body the room is handed stays current
                    // between sweeps for anyone reading it over REST.
                    trackChanges
                    isSynced={collaboration.isSynced}
                    initiativeId={Number.isFinite(initiativeId) ? initiativeId : null}
                    subject={`wiki_page:${pageId}`}
                    supportsEntityMentions
                    compact
                  />
                </>
              ) : (
                <div className="space-y-4">
                  <Skeleton className="h-10 w-2/3" />
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-11/12" />
                  <Skeleton className="h-4 w-4/5" />
                </div>
              )}
            </div>
          </div>

          {/* The rail: where this page leads. The contents of the page itself
              are in the sidebar, under the page — one outline, in the column
              that already carries the navigation.

              Beside the words when there is gutter for it, which is the width
              at which opening it moves nothing. */}
          {railOpen && railFitsBeside ? (
            <div className="flex w-72 shrink-0 flex-col overflow-y-auto py-6 pr-6">
              <WikiPageConnections wikiId={wikiId} pageId={pageId} className="min-h-0" />
            </div>
          ) : null}
        </div>
      </div>

      {/* Too narrow to sit beside the words, so it opens over them instead —
          the control means the same thing at every width. */}
      <Sheet
        open={railOpen && !railFitsBeside && railAsked}
        onOpenChange={(open) => !open && setShowConnections(false)}
      >
        <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-sm">
          <SheetHeader className="border-b px-5 py-4">
            <SheetTitle>{t("links.title")}</SheetTitle>
          </SheetHeader>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            <WikiPageConnections wikiId={wikiId} pageId={pageId} className="border-0 shadow-none" />
          </div>
        </SheetContent>
      </Sheet>

      {/* Hidden until asked for: browsing a wiki is reading it, and the
          conversation about it is a different activity. */}
      <Sheet open={commentsOpen} onOpenChange={setCommentsOpen}>
        <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-lg">
          <SheetHeader className="border-b px-5 py-4">
            <SheetTitle>{t("comments")}</SheetTitle>
          </SheetHeader>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            <ToolCommentsPanel tool={Tool.wiki} entity={wiki} />
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
};
