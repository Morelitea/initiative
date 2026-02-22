import { memo, useEffect, useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { CircleChevronRight } from "lucide-react";

import { getItem, setItem } from "@/lib/storage";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { guildPath } from "@/lib/guildUrl";
import { buildTagTree, type TagTreeNode } from "@/lib/tagTree";
import type { TagRead as TagType } from "@/api/generated/initiativeAPI.schemas";

// Maximum visual indentation depth (children still render, just don't indent further)
const MAX_TAG_INDENT = 3;

export interface TagBrowserProps {
  tags: TagType[];
  isLoading: boolean;
  activeGuildId: number | null;
}

export const TagBrowser = ({ tags, isLoading, activeGuildId }: TagBrowserProps) => {
  const { t } = useTranslation("nav");
  const tagTree = useMemo(() => buildTagTree(tags), [tags]);

  if (isLoading) {
    return (
      <div className="space-y-2 px-4">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  }

  if (tags.length === 0) {
    return <div className="text-muted-foreground px-4 py-2 text-sm">{t("noTagsCreated")}</div>;
  }

  return (
    <div className="space-y-1">
      {tagTree.map((node) => (
        <TagTreeNodeComponent
          key={node.fullPath}
          node={node}
          depth={0}
          activeGuildId={activeGuildId}
        />
      ))}
    </div>
  );
};

interface TagTreeNodeComponentProps {
  node: TagTreeNode;
  depth: number;
  activeGuildId: number | null;
}

const TagTreeNodeComponent = memo(({ node, depth, activeGuildId }: TagTreeNodeComponentProps) => {
  const { t } = useTranslation("nav");
  // Helper to create guild-scoped paths
  const gp = (path: string) => (activeGuildId ? guildPath(activeGuildId, path) : path);
  const [isOpen, setIsOpen] = useState(() => {
    try {
      const stored = getItem("tag-group-collapsed-states");
      if (stored) {
        const states = JSON.parse(stored) as Record<string, boolean>;
        return states[node.fullPath] ?? false;
      }
    } catch {
      // Ignore parsing errors
    }
    return false;
  });

  useEffect(() => {
    try {
      const stored = getItem("tag-group-collapsed-states");
      const states = stored ? (JSON.parse(stored) as Record<string, boolean>) : {};
      states[node.fullPath] = isOpen;
      setItem("tag-group-collapsed-states", JSON.stringify(states));
    } catch {
      // Ignore storage errors
    }
  }, [isOpen, node.fullPath]);

  const hasChildren = node.children.length > 0;
  const canExpand = hasChildren;

  // Get color from this node's tag, or first descendant with a tag
  const getNodeColor = (n: TagTreeNode): string | undefined => {
    if (n.tag?.color) return n.tag.color;
    for (const child of n.children) {
      const color = getNodeColor(child);
      if (color) return color;
    }
    return undefined;
  };
  const nodeColor = getNodeColor(node);

  // Count all descendant tags (for display)
  const countDescendants = (n: TagTreeNode): number => {
    let count = 0;
    for (const child of n.children) {
      if (child.tag) count++;
      count += countDescendants(child);
    }
    return count;
  };
  const descendantCount = countDescendants(node);

  // Leaf node (no children) - simple clickable item
  if (!hasChildren) {
    if (!node.tag) return null; // Ghost node with no tag and no children
    return (
      <Link
        to={gp(`/tags/${node.tag.id}`)}
        className="hover:bg-accent flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors"
      >
        <span
          className="h-3 w-3 shrink-0 rounded-full"
          style={{ backgroundColor: node.tag.color }}
        />
        <span className="min-w-0 flex-1 truncate">{node.segment}</span>
      </Link>
    );
  }

  // Node with children - collapsible
  return (
    <Collapsible open={isOpen} onOpenChange={canExpand ? setIsOpen : undefined}>
      <div className="flex items-center">
        {canExpand ? (
          <CollapsibleTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 shrink-0"
              aria-label={isOpen ? t("collapse") : t("expand")}
            >
              <CircleChevronRight
                className={cn("h-4 w-4 transition-transform", isOpen && "rotate-90")}
                style={{ color: nodeColor || undefined }}
              />
            </Button>
          </CollapsibleTrigger>
        ) : (
          <span className="flex h-7 w-7 shrink-0 items-center justify-center">
            <span
              className="h-3 w-3 rounded-full"
              style={{ backgroundColor: nodeColor || undefined }}
            />
          </span>
        )}
        {node.tag ? (
          <Link
            to={gp(`/tags/${node.tag.id}`)}
            className="hover:bg-accent flex min-w-0 flex-1 items-center gap-2 rounded-md px-1 py-1.5 text-sm transition-colors"
          >
            <span className="min-w-0 flex-1 truncate font-medium">{node.segment}</span>
            <span className="text-muted-foreground shrink-0 text-xs">{descendantCount}</span>
          </Link>
        ) : (
          <span className="flex min-w-0 flex-1 items-center gap-2 px-1 py-1.5 text-sm">
            <span className="min-w-0 flex-1 truncate font-medium">{node.segment}</span>
            <span className="text-muted-foreground shrink-0 text-xs">{descendantCount}</span>
          </span>
        )}
      </div>
      {canExpand && isOpen && (
        <CollapsibleContent
          className={cn("space-y-0.5 border-l pl-2", depth < MAX_TAG_INDENT && "ml-3")}
          style={{ borderColor: nodeColor || undefined }}
          forceMount
        >
          {node.children.map((child) => (
            <TagTreeNodeComponent
              key={child.fullPath}
              node={child}
              depth={depth + 1}
              activeGuildId={activeGuildId}
            />
          ))}
        </CollapsibleContent>
      )}
    </Collapsible>
  );
});
TagTreeNodeComponent.displayName = "TagTreeNodeComponent";
