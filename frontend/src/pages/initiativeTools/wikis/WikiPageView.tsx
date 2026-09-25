import { useLocation, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import type { SerializedEditorState } from "lexical";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool, WikiReadingWidth } from "@/api/generated/initiativeAPI.schemas";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { Editor } from "@/components/documents/editor/editor";
import { WikiChrome } from "@/components/initiativeTools/wikis/WikiChrome";
import { WikiPageConnections } from "@/components/initiativeTools/wikis/WikiPageConnections";
import { WikiPageNav } from "@/components/initiativeTools/wikis/WikiPageNav";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useCollaboration } from "@/hooks/useCollaboration";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useReadOnOpen } from "@/hooks/useNotifications";
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

  // The newest body regardless of whether it has been sent, which is what the
  // reading view is shown the moment somebody stops writing. The server hears
  // about a body on a pause and, in a live room, writes it on a sweep of its
  // own — both of which finish long after the eye does.
  const latestBody = useRef<{ pageId: number; state: SerializedEditorState } | null>(null);
  // What this tab last rendered, for the room to save as the page leaves.
  const finalContent = useCallback(() => {
    const latest = latestBody.current;
    return latest && latest.pageId === pageId ? latest.state : undefined;
  }, [pageId]);

  // Live co-editing, over the same room documents use — a page is just
  // another body the server keeps a Yjs document for. The path names the page
  // through its wiki, the way every other address for it does.
  const collaboration = useCollaboration({
    socketPath: validIds ? `wikis/${wikiId}/pages/${pageId}/collaborate` : null,
    // Only while somebody is writing. A wiki is read far more than it is
    // written, so a reader opens no room and costs the server nothing.
    enabled: validIds && editWanted,
    finalContent,
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
  // Editing needs both the right and the intent — somebody who may write is
  // still reading until they say otherwise.
  const isEditing = canWrite && editWanted;

  // The title is edited in place, and saved on a pause rather than on every
  // keystroke — renaming a page rewrites its slug, which is an address.
  //
  // What is being typed carries the page it is being typed INTO. Following a
  // link swaps the page under this component without remounting it, so a name
  // still waiting out its pause would otherwise be saved against whichever
  // page is open when the pause ends — the page you arrive at taking the name
  // of the page you came from.
  const [draft, setDraft] = useState<{ pageId: number; title: string } | null>(null);
  // What the server has already been told, so a pause and the blur behind it
  // do not both send the same rename. Cleared when the page changes.
  const sentTitle = useRef<string | null>(null);
  const loadedPageId = pageQuery.data?.id;
  useReadOnOpen("wiki_page", loadedPageId);
  const loadedTitle = pageQuery.data?.title;
  useEffect(() => {
    sentTitle.current = null;
  }, [pageId]);
  useEffect(() => {
    if (loadedPageId === undefined) return;
    // Our own rename coming back from the server is not news, and the field
    // may have moved on since it was sent — so it is left as it is.
    if (sentTitle.current !== null && sentTitle.current === (loadedTitle ?? "")) return;
    sentTitle.current = null;
    setDraft({ pageId: loadedPageId, title: loadedTitle ?? "" });
  }, [loadedPageId, loadedTitle]);

  const debouncedDraft = useDebouncedValue(draft, 600);

  // One rename, however it is asked for — by the pause, or by leaving the
  // field, which is what a click straight into the tree does.
  const rename = useCallback(
    (pending: { pageId: number; title: string } | null) => {
      // `current` is compared, not required: a page starts with no name, and
      // naming one is the first thing anybody does to it.
      const current = pageQuery.data?.title ?? "";
      const next = pending?.title.trim() ?? "";
      if (!canWrite || !pending || pending.pageId !== pageId) return;
      if (!next || next === current || next === sentTitle.current) return;
      sentTitle.current = next;
      savePage({ title: next });
    },
    [canWrite, pageId, pageQuery.data?.title, savePage]
  );

  useEffect(() => {
    rename(debouncedDraft);
  }, [debouncedDraft, rename]);

  // What the field shows: what is being typed, or — in the moment between
  // following a link and that page arriving — the name of the page we are on.
  const draftTitle = draft?.pageId === pageId ? draft.title : (pageQuery.data?.title ?? "");

  // The editor reports every keystroke; the server hears about them 2s after
  // somebody stops, the same window a document autosaves on. Saving per change
  // would be a request per character — and each one re-reads the body for the
  // links it names.
  // The newest body, and a counter that says one arrived. The body itself is a
  // ref so a keystroke does not re-render the editor around the person typing.
  // It names its page for the same reason the title draft does: the words are
  // only ever meant for the page they were typed into.
  const pendingBody = useRef<{ pageId: number; state: SerializedEditorState } | null>(null);
  const [bodyRevision, setBodyRevision] = useState(0);
  const [writtenBody, setWrittenBody] = useState<{
    pageId: number;
    state: SerializedEditorState;
    at: number;
  } | null>(null);

  const onBodyChange = useCallback(
    (state: SerializedEditorState) => {
      if (!canWrite) return;
      pendingBody.current = { pageId, state };
      latestBody.current = { pageId, state };
      setBodyRevision((revision) => revision + 1);
    },
    [canWrite, pageId]
  );

  // A page's words never travel to another page, not even in a ref. Which
  // page they belong to is read from the address, and an address being
  // followed names no page for a moment — so this waits for the next real one
  // rather than treating that moment as a page of its own.
  const bodyOwner = useRef(pageId);
  useEffect(() => {
    if (!Number.isFinite(pageId) || bodyOwner.current === pageId) return;
    bodyOwner.current = pageId;
    pendingBody.current = null;
    latestBody.current = null;
    setWrittenBody(null);
  }, [pageId]);

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
      // Words left over from the page before are not this page's words, and
      // the page they were written into has been rebuilt behind us.
      if (body.pageId !== pageId) return;
      if (isCollaborating) {
        sendContent(body.state);
        return;
      }
      savePage({ content: body.state as unknown as Record<string, unknown> });
    }, 2000);
    return () => clearTimeout(timer);
  }, [bodyRevision, pageId, savePage, isCollaborating, sendContent]);

  // A page nobody has typed in yet is stored as `{}` — the column's default —
  // and a root with no children is the same thing said differently. Lexical
  // refuses either as a starting state, so both are handed over as "no state"
  // and it builds its own empty document.
  const servedBody = useMemo(() => {
    const stored = pageQuery.data?.content as SerializedEditorState | undefined;
    const children = stored?.root?.children;
    return Array.isArray(children) && children.length > 0 ? stored : null;
  }, [pageQuery.data?.content]);

  const wiki = wikiQuery.data;
  const page = pageQuery.data;

  // Putting the eye back on. What was just typed is kept for the reading view,
  // and what has not been sent is sent now rather than waiting out a pause
  // nobody is going to finish — otherwise the page is read back as it was
  // before the edit, or as nothing at all if it had never been written to.
  const wasEditing = useRef(false);
  useEffect(() => {
    if (!validIds) return;
    if (isEditing) {
      wasEditing.current = true;
      return;
    }
    if (!wasEditing.current) return;
    wasEditing.current = false;

    const written = latestBody.current;
    if (!written || written.pageId !== pageId) return;
    setWrittenBody({ ...written, at: Date.now() });

    const unsent = pendingBody.current;
    if (!unsent || unsent.pageId !== pageId) return;
    pendingBody.current = null;
    if (isCollaborating) {
      sendContent(unsent.state);
      return;
    }
    savePage({ content: unsent.state as unknown as Record<string, unknown> });
  }, [isEditing, validIds, pageId, isCollaborating, sendContent, savePage]);

  // What the editor is handed, and a token that changes with it.
  //
  // Lexical reads its starting state ONCE, at mount, so a body that arrives
  // later — the save that just landed, the page you clicked — only reaches the
  // screen if the editor is rebuilt for it. The token is part of the reading
  // key alone: rebuilding the editor somebody is typing in would take their
  // cursor with it.
  const ownBody = writtenBody?.pageId === pageId ? writtenBody : null;
  const body = ownBody?.state ?? servedBody;
  const bodyToken = ownBody ? `own:${ownBody.at}` : `served:${page?.updated_at ?? "none"}`;

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
      {},
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
  // Asked for, allowed by the wiki, and there is a page to have connections.
  const railOpen = showConnections && wiki.show_connections && Boolean(page);

  return (
    <>
      <div className="flex h-full min-h-0 flex-col">
        <WikiChrome
          wiki={wiki}
          pageTitle={isEditing ? draftTitle : page?.title || t("pages.untitled")}
          onRename={isEditing ? (value) => setDraft({ pageId, title: value }) : undefined}
          // Leaving the field sends the name now. Clicking a page in the tree
          // blurs before it navigates, so a rename typed and immediately
          // walked away from lands on the page it was typed into.
          onRenameCommit={isEditing ? () => rename(draft) : undefined}
          pageUpdatedAt={page?.updated_at}
          canWrite={canWrite}
          editing={isEditing}
          isDraft={page?.is_draft ?? false}
          onPublish={() =>
            savePage({ is_draft: false }, { onSuccess: () => toast.success(t("page.published")) })
          }
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
              {/* The row has to BE this page: a body from the page before it
                  is not this page's body, however briefly it is held. */}
              {page && page.id === pageId ? (
                <>
                  <Editor
                    // Rebuilt rather than switched: the editor captures
                    // whether it is collaborative at first mount and never
                    // re-reads it, so flipping that on a live instance is
                    // outside its contract. Changing the key hands it a fresh
                    // one for the mode being entered.
                    key={`${pageId}:${isEditing ? "edit" : `read:${bodyToken}`}`}
                    editorSerializedState={body ?? undefined}
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
                    // Being read, the body has no sheet of its own and the
                    // reading column is its gutter. Being written, it is back
                    // inside a bordered editor, and words against that border
                    // are words with no margin — so it takes the same gutter a
                    // document's editor does.
                    compact={!isEditing}
                  />
                  {/* Where to go from here. Reading furniture: somebody who is
                      writing is not looking for the way out of the page. */}
                  {isEditing ? null : (
                    <WikiPageNav wikiId={wikiId} initiativeId={initiativeId} currentId={pageId} />
                  )}
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
            {/* The page's thread, not the wiki's: a note about the rota
                belongs on the rota. The wiki still answers for whether there
                is one at all, and for who may read it. */}
            <ToolCommentsPanel
              tool={Tool.wiki}
              entity={wiki}
              target={{ type: "wiki_page", id: pageId }}
            />
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
};
