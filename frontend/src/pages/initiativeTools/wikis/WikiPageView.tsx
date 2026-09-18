import { Link, useParams } from "@tanstack/react-router";
import type { SerializedEditorState } from "lexical";
import { ArrowUpRight, Link2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { WikiPageLink } from "@/api/generated/initiativeAPI.schemas";
import { Editor } from "@/components/documents/editor/editor";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useUpdateWikiPage, useWiki, useWikiPage, useWikiPageLinks } from "@/hooks/useWikis";
import { useGuildPath } from "@/lib/guildUrl";
import { entityRefRoute, toolKebabSingular, wikiPageRoute } from "@/lib/tools";

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

  const wikiId = Number(wikiIdParam);
  const pageId = Number(pageIdParam);
  const initiativeId = Number(initiativeIdParam);
  const validIds = Number.isFinite(wikiId) && Number.isFinite(pageId);

  const wikiQuery = useWiki(validIds ? wikiId : null);
  const pageQuery = useWikiPage(validIds ? wikiId : null, validIds ? pageId : null);
  const linksQuery = useWikiPageLinks(validIds ? wikiId : null, validIds ? pageId : null);
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

  useEffect(() => {
    if (bodyRevision === 0 || pendingBody.current === null) return;
    const timer = setTimeout(() => {
      const body = pendingBody.current;
      if (body === null) return;
      pendingBody.current = null;
      savePage({ content: body as unknown as Record<string, unknown> });
    }, 2000);
    return () => clearTimeout(timer);
  }, [bodyRevision, savePage]);

  const initialBody = useMemo(
    () => (pageQuery.data?.content ?? null) as SerializedEditorState | null,
    [pageQuery.data?.content]
  );

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

  if (pageQuery.isLoading) {
    return <p className="p-6 text-muted-foreground text-sm">{t("pages.loading")}</p>;
  }

  const incoming = linksQuery.data?.incoming ?? [];
  const outgoing = linksQuery.data?.outgoing ?? [];

  /**
   * Where a link points.
   *
   * A page of any wiki is addressed directly — the server sends the wiki and
   * the initiative along with the link, so nothing has to be looked up. Every
   * other kind goes through `/go`, which resolves the id to wherever it lives.
   */
  const hrefOf = (link: WikiPageLink) => {
    if (link.entity_type === "wiki_page" && link.tool_id != null) {
      return wikiPageRoute(link.initiative_id ?? null, link.tool_id, link.entity_id);
    }
    return entityRefRoute(toolKebabSingular(link.entity_type as never), link.entity_id);
  };

  const renderLink = (link: WikiPageLink) => (
    <li key={`${link.entity_type}-${link.entity_id}-${link.relationship_type}`}>
      <Link
        to={gp(hrefOf(link))}
        className="flex items-center gap-1.5 rounded-md px-2 py-1 text-sm hover:bg-accent/50"
      >
        <ArrowUpRight className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <span className="truncate">{link.title}</span>
      </Link>
    </li>
  );

  return (
    <div className="mx-auto w-full max-w-3xl space-y-8 p-6">
      <Input
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        readOnly={!canWrite}
        aria-label={t("pages.titleLabel")}
        placeholder={t("pages.titlePlaceholder")}
        className="!text-3xl h-auto border-0 px-0 font-bold shadow-none focus-visible:ring-0"
      />

      <Editor
        key={pageId}
        editorSerializedState={initialBody ?? undefined}
        onSerializedChange={onBodyChange}
        readOnly={!canWrite}
        initiativeId={Number.isFinite(initiativeId) ? initiativeId : null}
        subject={`wiki_page:${pageId}`}
        supportsEntityMentions
        compact
      />

      <section className="space-y-3 border-t pt-6">
        <h2 className="flex items-center gap-1.5 font-semibold text-sm">
          <Link2 className="size-4 text-muted-foreground" aria-hidden />
          {t("links.title")}
        </h2>

        {linksQuery.isLoading ? (
          <p className="text-muted-foreground text-sm">{t("links.loading")}</p>
        ) : incoming.length === 0 && outgoing.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("links.noneDescription")}</p>
        ) : (
          <div className="grid gap-6 sm:grid-cols-2">
            {outgoing.length > 0 ? (
              <div className="space-y-1">
                <h3 className="px-2 font-medium text-muted-foreground text-xs">
                  {t("links.outgoing")}
                </h3>
                <ul>{outgoing.map(renderLink)}</ul>
              </div>
            ) : null}
            {incoming.length > 0 ? (
              <div className="space-y-1">
                <h3 className="px-2 font-medium text-muted-foreground text-xs">
                  {t("links.incoming")}
                </h3>
                <ul>{incoming.map(renderLink)}</ul>
              </div>
            ) : null}
          </div>
        )}
      </section>
    </div>
  );
};
