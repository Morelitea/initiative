/**
 * THE breadcrumb trail for every tool surface: Initiative → tool list →
 * whatever the page adds (the entity, a content item beneath it, "Settings").
 * The initiative and tool-list crumbs are derived from the `Tool` enum via
 * `src/lib/tools.ts`, so a new tool's pages get the right shape for free and
 * every existing tool renders the same shape by construction rather than by
 * each page hand-rolling its own.
 */
import { Link } from "@tanstack/react-router";
import { Fragment, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { useInitiativeName } from "@/hooks/useInitiatives";
import { useGuildPath } from "@/lib/guildUrl";
import { toolListRoute, toolNavLabelKey } from "@/lib/tools";

export interface ToolBreadcrumbSegment {
  label: ReactNode;
  /** Guild-relative path (e.g. from `toolDetailRoute`). Omit on the last
   *  segment — it renders as the current page instead of a link. */
  to?: string;
}

export interface ToolBreadcrumbProps {
  tool: Tool;
  /** The initiative this entity lives in. Omit (or null) for a guild-level
   *  entity (e.g. a calendar with no initiative) — that crumb is dropped. */
  initiativeId?: number | null;
  /** Segments after the tool-list crumb, in order: the entity, a content item
   *  beneath it, "Settings" — whichever apply on this page. The last one
   *  renders as the current page; every earlier one needs a `to`. Leave empty
   *  when the tool-list page itself is the current page. */
  trail?: ToolBreadcrumbSegment[];
}

export const ToolBreadcrumb = ({ tool, initiativeId, trail = [] }: ToolBreadcrumbProps) => {
  const { t } = useTranslation("nav");
  const gp = useGuildPath();
  const initiativeName = useInitiativeName(initiativeId);
  const toolListIsCurrentPage = trail.length === 0;

  return (
    <Breadcrumb>
      <BreadcrumbList>
        {initiativeName && (
          <>
            <BreadcrumbItem>
              <BreadcrumbLink asChild>
                <Link to={gp(`/initiatives/${initiativeId}`)}>{initiativeName}</Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
          </>
        )}
        <BreadcrumbItem>
          {toolListIsCurrentPage ? (
            <BreadcrumbPage>{t(toolNavLabelKey(tool))}</BreadcrumbPage>
          ) : (
            <BreadcrumbLink asChild>
              <Link to={gp(toolListRoute(tool))}>{t(toolNavLabelKey(tool))}</Link>
            </BreadcrumbLink>
          )}
        </BreadcrumbItem>
        {trail.map((segment, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: trail is a fixed, caller-provided sequence — position is the identity
          <Fragment key={index}>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              {segment.to ? (
                <BreadcrumbLink asChild>
                  <Link to={gp(segment.to)}>{segment.label}</Link>
                </BreadcrumbLink>
              ) : (
                <BreadcrumbPage>{segment.label}</BreadcrumbPage>
              )}
            </BreadcrumbItem>
          </Fragment>
        ))}
      </BreadcrumbList>
    </Breadcrumb>
  );
};
