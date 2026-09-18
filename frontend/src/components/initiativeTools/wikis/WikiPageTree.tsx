import { Link } from "@tanstack/react-router";
import { ChevronRight, FileText, Home, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { WikiPageSummary } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** A page plus the pages filed under it. Built once from the flat list. */
export interface WikiTreeNode {
  page: WikiPageSummary;
  children: WikiTreeNode[];
}

/**
 * Build the nesting the server deliberately does not send.
 *
 * The API returns pages flat, each naming its parent, because that is the
 * shape a move writes and the shape a lookup wants. The nesting is a view of
 * it, so it is derived here rather than transported.
 *
 * A page whose parent is not in the list is treated as top-level. That happens
 * while a move is in flight, and a page that briefly draws at the root is a far
 * better failure than one that vanishes.
 */
export const buildWikiTree = (pages: WikiPageSummary[]): WikiTreeNode[] => {
  const nodes = new Map<number, WikiTreeNode>(
    pages.map((page) => [page.id, { page, children: [] }])
  );
  const roots: WikiTreeNode[] = [];
  for (const page of pages) {
    const node = nodes.get(page.id);
    if (!node) continue;
    const parent = page.parent_page_id === null ? undefined : nodes.get(page.parent_page_id);
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  return roots;
};

interface WikiPageTreeProps {
  pages: WikiPageSummary[];
  /** Which page is open, so the tree can mark it and open its ancestors. */
  activePageId?: number | null;
  /** The wiki's chosen home page, marked so it reads as the way in. */
  homePageId?: number | null;
  /** Builds the link for a page. The tree does not know the route shape. */
  hrefOf: (page: WikiPageSummary) => string;
  /** Offered per row when the reader may write. Omitted otherwise. */
  onAddChild?: (parent: WikiPageSummary) => void;
  className?: string;
}

/**
 * A wiki's pages, as the tree they sit in.
 *
 * Rows are links rather than buttons — a page is an address, and opening one
 * in a new tab is something people do with a handbook — and the disclosure
 * triangle is a separate control so that following a link and expanding its
 * children are never the same click.
 */
export const WikiPageTree = ({
  pages,
  activePageId,
  homePageId,
  hrefOf,
  onAddChild,
  className,
}: WikiPageTreeProps) => {
  const { t } = useTranslation("wikis");
  const tree = useMemo(() => buildWikiTree(pages), [pages]);

  // The ancestors of the open page. A branch somebody collapsed is forced back
  // open when the page they navigate to lives inside it — otherwise following a
  // link from the body would appear to do nothing.
  const ancestors = useMemo(() => {
    const byId = new Map(pages.map((page) => [page.id, page]));
    const chain = new Set<number>();
    let current = activePageId == null ? undefined : byId.get(activePageId);
    while (current?.parent_page_id != null) {
      chain.add(current.parent_page_id);
      current = byId.get(current.parent_page_id);
    }
    return chain;
  }, [pages, activePageId]);

  // Expanded is the default — a wiki is a thing you skim — so this records the
  // branches somebody has deliberately folded away.
  const [collapsed, setCollapsed] = useState<ReadonlySet<number>>(new Set());
  const isOpen = (id: number) => !collapsed.has(id) || ancestors.has(id);

  const toggle = (id: number) =>
    setCollapsed((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const renderNode = (node: WikiTreeNode, depth: number) => {
    const { page, children } = node;
    const hasChildren = children.length > 0;
    const open = isOpen(page.id);
    const active = page.id === activePageId;

    return (
      <li key={page.id}>
        <div
          className={cn(
            "group flex items-center gap-0.5 rounded-md pr-1 transition",
            active ? "bg-accent text-accent-foreground" : "hover:bg-accent/50"
          )}
          style={{ paddingLeft: `${depth * 12}px` }}
        >
          {hasChildren ? (
            <button
              type="button"
              onClick={() => toggle(page.id)}
              className="flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground hover:text-foreground"
              aria-expanded={open}
              aria-label={open ? t("pages.collapse") : t("pages.expand")}
            >
              <ChevronRight
                className={cn("size-3.5 transition-transform", open && "rotate-90")}
                aria-hidden
              />
            </button>
          ) : (
            <span className="size-5 shrink-0" />
          )}

          <Link
            to={hrefOf(page)}
            className="flex min-w-0 flex-1 items-center gap-1.5 py-1 text-sm"
            title={page.title}
          >
            {page.id === homePageId ? (
              <Home
                className="size-3.5 shrink-0 text-muted-foreground"
                aria-label={t("pages.isHome")}
              />
            ) : (
              <FileText className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
            )}
            <span className="truncate">{page.title || t("pages.untitled")}</span>
          </Link>

          {onAddChild ? (
            <Button
              variant="ghost"
              size="icon"
              className="size-6 shrink-0 opacity-0 transition focus-visible:opacity-100 group-hover:opacity-100"
              onClick={() => onAddChild(page)}
              aria-label={t("pages.newSubPage")}
            >
              <Plus className="size-3.5" aria-hidden />
            </Button>
          ) : null}
        </div>

        {hasChildren && open ? (
          <ul className="space-y-px">{children.map((child) => renderNode(child, depth + 1))}</ul>
        ) : null}
      </li>
    );
  };

  if (pages.length === 0) {
    return (
      <p className={cn("px-2 py-1.5 text-muted-foreground text-sm", className)}>
        {t("pages.empty")}
      </p>
    );
  }

  return (
    <nav className={className} aria-label={t("pages.title")}>
      <ul className="space-y-px">{tree.map((node) => renderNode(node, 0))}</ul>
    </nav>
  );
};
