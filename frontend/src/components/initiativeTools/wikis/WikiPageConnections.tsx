import { Link } from "@tanstack/react-router";
import { ArrowUpRight, CornerDownRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { WikiPageLink } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useWikiPageLinks } from "@/hooks/useWikis";
import { useGuildPath } from "@/lib/guildUrl";
import { entityRefRoute, TOOL_ICONS, toolKebabSingular, wikiPageRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

/**
 * The icon a link wears, by what it points at.
 *
 * A page gets the wiki's own; anything else gets its tool's, so a task reads as
 * a task at a glance. Sub-resources that are not tools fall back to the tool
 * that governs them, which the server already sends.
 */
const iconFor = (link: WikiPageLink) => {
  if (link.entity_type === "wiki_page") return TOOL_ICONS[Tool.wiki];
  const tool = link.tool as Tool | null;
  return tool && TOOL_ICONS[tool] ? TOOL_ICONS[tool] : null;
};

/**
 * Where a link points.
 *
 * A page of any wiki is addressed directly — the server sends the wiki and the
 * initiative with the link, so nothing has to be looked up. Everything else
 * goes through `/go`, which resolves the id to wherever it lives.
 */
const hrefOf = (link: WikiPageLink) => {
  if (link.entity_type === "wiki_page" && link.tool_id != null) {
    return wikiPageRoute(link.initiative_id ?? null, link.tool_id, link.entity_id);
  }
  return entityRefRoute(toolKebabSingular(link.entity_type as never), link.entity_id);
};

const LinkList = ({ links, heading }: { links: WikiPageLink[]; heading: string }) => {
  const gp = useGuildPath();
  if (links.length === 0) return null;

  return (
    <div className="space-y-0.5">
      <h3 className="px-2 font-medium text-muted-foreground text-xs">{heading}</h3>
      <ul>
        {links.map((link) => {
          const Icon = iconFor(link);
          return (
            <li key={`${link.entity_type}-${link.entity_id}-${link.relationship_type}`}>
              <Link
                to={gp(hrefOf(link))}
                className="flex items-center gap-1.5 rounded-md px-2 py-1 text-sm hover:bg-accent/50"
                title={link.title}
              >
                {Icon ? (
                  <Icon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                ) : (
                  <CornerDownRight
                    className="size-3.5 shrink-0 text-muted-foreground"
                    aria-hidden
                  />
                )}
                <span className="truncate">{link.title}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
};

/**
 * What this page connects to, beside the page.
 *
 * A wiki is explored rather than administered, so this is a way *through* the
 * web rather than a place to manage it: every row is one click to the thing it
 * names, and there is nothing here to configure. Links are made by writing
 * them — `[[` in the body — which is the same gesture that makes them
 * anywhere else in the app.
 *
 * It sits under the contents in the rail because the two answer the same kind
 * of question: contents is where to go inside this page, this is where to go
 * out of it.
 */
export const WikiPageConnections = ({
  wikiId,
  pageId,
  className,
}: {
  wikiId: number;
  pageId: number;
  className?: string;
}) => {
  const { t } = useTranslation("wikis");
  const linksQuery = useWikiPageLinks(wikiId, pageId);

  const outgoing = linksQuery.data?.outgoing ?? [];
  const incoming = linksQuery.data?.incoming ?? [];
  const empty = outgoing.length === 0 && incoming.length === 0;

  return (
    <aside
      className={cn(
        "flex min-h-0 flex-col overflow-hidden rounded-lg border bg-card shadow",
        className
      )}
    >
      <div className="flex items-center gap-1.5 border-b px-3 py-2 font-medium text-sm">
        <ArrowUpRight className="size-3.5 text-muted-foreground" aria-hidden />
        {t("links.title")}
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-2">
        {linksQuery.isLoading ? (
          <p className="px-1 text-muted-foreground text-sm">{t("links.loading")}</p>
        ) : empty ? (
          <p className="px-1 text-muted-foreground text-sm">{t("links.noneDescription")}</p>
        ) : (
          <>
            <LinkList links={outgoing} heading={t("links.outgoing")} />
            <LinkList links={incoming} heading={t("links.incoming")} />
          </>
        )}
      </div>
    </aside>
  );
};
