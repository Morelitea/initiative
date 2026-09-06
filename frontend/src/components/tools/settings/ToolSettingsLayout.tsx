/**
 * THE settings frame every tool gets.
 *
 * Rename, describe, tag, share, and delete are identical for all six tools, so
 * they live here once. Everything the frame needs is derived from the `tool`
 * value — breadcrumb labels, section routes, the tag mutation — and all of its
 * copy comes from the shared `common:toolSettings.*` namespace, so adding a
 * tool costs a wrapper that names its data hooks and nothing else.
 *
 * The sections are real routes — `/settings/access` is a place, not a piece of
 * component state — so sharing can be linked to, and the back button walks
 * back through the sections that were visited. The bar still looks and behaves
 * like tabs; selecting one navigates.
 *
 * A tool with genuinely extra settings passes cards as `detailsExtra` /
 * `advancedExtra`, or names a whole extra section in `extraTabs` and serves it
 * from a route beside the shared ones; the shell stays the same shape for
 * every tool.
 */

import { Outlet, useLocation, useRouter } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ResourceGrantSchema, Tool } from "@/api/generated/initiativeAPI.schemas";
import { SettingsTabsNav } from "@/components/settings/SettingsTabsNav";
import {
  type ToolMutation,
  type ToolSettingsEntity,
  ToolSettingsProvider,
} from "@/components/tools/settings/ToolSettingsContext";
import { ToolBreadcrumb } from "@/components/tools/ToolBreadcrumb";
import { extractSubPath, isGuildScopedPath, useGuildPath } from "@/lib/guildUrl";
import { hasWriteAccess } from "@/lib/permissions";
import { matchActiveTab } from "@/lib/tabs";
import {
  TOOL_SETTINGS_DEFAULT_SECTION,
  toolDetailRoute,
  toolSettingsSectionRoute,
} from "@/lib/tools";

export type { ToolMutation, ToolSettingsEntity };

export interface ToolSettingsLayoutProps {
  tool: Tool;
  entity: ToolSettingsEntity | undefined;
  isLoading: boolean;
  isError: boolean;
  /**
   * The rename/describe mutation. Omit it to drop the built-in details form —
   * projects save those fields through their own richer form, and a document's
   * name is edited in the editor.
   */
  update?: ToolMutation<{ name?: string; description?: string | null }>;
  setGrants: ToolMutation<ResourceGrantSchema[]>;
  remove: ToolMutation<number>;
  /** Extra cards for the Details section, e.g. a project's dates or a calendar's color. */
  detailsExtra?: ReactNode;
  /** Extra cards for the Advanced section, e.g. duplicate, archive, or export. */
  advancedExtra?: ReactNode;
  /**
   * Whole extra sections, for settings too large to sit in a card (project
   * task statuses). Each `value` is the route segment serving it, so a tab
   * named here needs a route file beside the shared sections.
   */
  extraTabs?: { value: string; label: string }[];
  /** Rendered outside the sections — dialogs a tool's extras need. */
  children?: ReactNode;
}

export const ToolSettingsLayout = ({
  tool,
  entity,
  isLoading,
  isError,
  update,
  setGrants,
  remove,
  detailsExtra,
  advancedExtra,
  extraTabs = [],
  children,
}: ToolSettingsLayoutProps) => {
  const { t } = useTranslation(["common", "nav", "access"]);
  const router = useRouter();
  const gp = useGuildPath();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("common:loading")}
      </div>
    );
  }

  if (isError || !entity) {
    return <p className="text-destructive">{t("common:toolSettings.notFound")}</p>;
  }

  const canManage = hasWriteAccess(entity.my_permission_level);
  const isOwner = entity.my_permission_level === "owner";

  const sectionPath = (section: string) =>
    gp(toolSettingsSectionRoute(tool, entity.initiative_id, entity.id, section));

  const tabs = [
    { value: "details", label: t("common:toolSettings.tabDetails"), path: sectionPath("details") },
    // The bar only offers sharing to someone who may change it; the section
    // refuses it too, for the address someone types.
    ...(canManage
      ? [
          {
            value: "access",
            label: t("common:toolSettings.tabAccess"),
            path: sectionPath("access"),
          },
        ]
      : []),
    ...extraTabs.map((tab) => ({
      value: tab.value,
      label: tab.label,
      path: sectionPath(tab.value),
    })),
    // Advanced holds a tool's own extra operations plus deletion, so it is
    // offered only when this entity has one of them to offer.
    ...(advancedExtra || isOwner
      ? [
          {
            value: "advanced",
            label: t("common:toolSettings.tabAdvanced"),
            path: sectionPath("advanced"),
          },
        ]
      : []),
  ];

  // The tab paths are guild-prefixed; matching happens on the sub-path, so a
  // guild id in the address never decides which tab is lit.
  const currentPath = location.pathname;
  const normalizedPath = isGuildScopedPath(currentPath)
    ? extractSubPath(currentPath).replace(/\/+$/, "") || "/"
    : currentPath.replace(/\/+$/, "") || "/";
  const activeTab = matchActiveTab(
    tabs.map((tab) => ({ value: tab.value, path: extractSubPath(tab.path) })),
    normalizedPath,
    TOOL_SETTINGS_DEFAULT_SECTION
  );

  return (
    <div className="space-y-6">
      <ToolBreadcrumb
        tool={tool}
        initiativeId={entity.initiative_id}
        trail={[
          { label: entity.name, to: toolDetailRoute(tool, entity.initiative_id, entity.id) },
          { label: t("common:toolSettings.title") },
        ]}
      />

      <div className="space-y-1">
        <h1 className="font-semibold text-3xl tracking-tight">{t("common:toolSettings.title")}</h1>
        <p className="text-muted-foreground text-sm">{t("common:toolSettings.description")}</p>
      </div>

      <SettingsTabsNav
        tabs={tabs}
        activeTab={activeTab}
        onNavigate={(path) => router.navigate({ to: path })}
      />

      <ToolSettingsProvider
        value={{
          tool,
          entity,
          canManage,
          isOwner,
          update,
          setGrants,
          remove,
          detailsExtra,
          advancedExtra,
        }}
      >
        <Outlet />
      </ToolSettingsProvider>

      {children}
    </div>
  );
};
